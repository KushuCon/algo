"""
strategies/scalp_5m.py — 5-Minute EMA Ribbon + MACD Momentum Scalper

HOW IT WORKS:
  The EMA ribbon (fast EMA8 vs slow EMA21) shows trend direction and strength.
  MACD histogram momentum confirms entries: we only buy when the histogram
  JUST turned positive (momentum accelerating upward) while price is above
  the fast EMA — this avoids chasing moves that already ran.

  Wider EMA separation = stronger trend = higher signal strength score.
  Narrower separation = choppy market = skip or reduce size.

ENTRY (BUY):
  1. EMA8 > EMA21 (ribbon in uptrend alignment)
  2. MACD histogram crossed from negative → positive THIS bar (fresh momentum)
  3. Price > EMA8 (not buying a dip inside the ribbon — wait for confirmation)
  4. Time filter: 09:45–15:30 ET (skip first 15min open volatility)

EXIT (SELL):
  1. MACD histogram crosses from positive → negative (momentum reversing)
  2. Price closes below EMA8 (trend structure broken)
  (Hard stop-loss / take-profit still handled by PortfolioManager)

SIGNAL STRENGTH:
  Based on EMA separation as % of price — wider ribbon = stronger trend.
  Capped at 1.0. Use this to scale position size in PortfolioManager.

BEST FOR:
  Trending intraday moves. Works well on index ETFs (SPY, QQQ) and
  high-beta names (NVDA, TSLA, AMZN). AVOID on low-volume symbols
  or when VIX > 30 (market-wide chop eats EMA signals).

PARAMETERS (add to config.py):
  SCALP5_EMA_FAST   = 8       # Fast EMA period
  SCALP5_EMA_SLOW   = 21      # Slow EMA period
  SCALP5_MACD_FAST  = 12      # MACD fast EMA
  SCALP5_MACD_SLOW  = 26      # MACD slow EMA
  SCALP5_MACD_SIG   = 9       # MACD signal line EMA
  SCALP5_MIN_RIBBON = 0.002   # Minimum EMA gap as % of price (filter chop)
  SCALP5_OPEN_SKIP  = "09:45" # Don't trade before this (skip open noise)
  SCALP5_EOD_CUTOFF = "15:30"

BACKTESTING NOTES:
  - Use 5Min bars: timeframe="5Min" in get_bars()
  - The MACD crossover check looks at hist[-1] vs hist[-2] — ensure you
    have at least MACD_SLOW + MACD_SIG + 5 bars before first signal
  - On SPY/QQQ this generates ~2-6 signals per day; more on volatile days
  - Best results historically: 10:00–12:00 and 14:00–15:00 ET windows
"""

from datetime import time as dtime
import pandas as pd
from strategies.base import BaseStrategy
from utils.indicators import ema, macd
from utils.helpers import now_et
import config


# ── Defaults (override in config.py) ─────────────────────────────────────────
EMA_FAST    = getattr(config, "SCALP5_EMA_FAST",    8)
EMA_SLOW    = getattr(config, "SCALP5_EMA_SLOW",   21)
MACD_FAST   = getattr(config, "SCALP5_MACD_FAST",  12)
MACD_SLOW   = getattr(config, "SCALP5_MACD_SLOW",  26)
MACD_SIG    = getattr(config, "SCALP5_MACD_SIG",    9)
MIN_RIBBON  = getattr(config, "SCALP5_MIN_RIBBON", 0.002)   # 0.2% min gap
OPEN_SKIP   = getattr(config, "SCALP5_OPEN_SKIP",  "09:45")
EOD_CUTOFF  = getattr(config, "SCALP5_EOD_CUTOFF", "15:30")


def _parse_time(t_str: str) -> dtime:
    h, m = map(int, t_str.split(":"))
    return dtime(h, m)


class ScalpFiveMin(BaseStrategy):
    """
    5-minute EMA ribbon + MACD histogram momentum scalper.
    Requires 5Min OHLCV bars from Alpaca (timeframe="5Min").
    """
    TIMEFRAME = "5Min"
    BAR_LIMIT = 200

    def __init__(self):
        super().__init__("Scalp 5Min")
        self.open_skip  = _parse_time(OPEN_SKIP)
        self.eod_cutoff = _parse_time(EOD_CUTOFF)
        self.log.info(
            f"Scalp5m | EMA({EMA_FAST}/{EMA_SLOW}) | "
            f"MACD({MACD_FAST},{MACD_SLOW},{MACD_SIG}) | "
            f"min_ribbon={MIN_RIBBON*100:.1f}% | "
            f"window={OPEN_SKIP}–{EOD_CUTOFF}"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _in_trading_window(self) -> bool:
        """Return True if we're between open_skip and eod_cutoff (US Eastern)."""
        now = now_et().time()
        return self.open_skip <= now < self.eod_cutoff

    def _hist_crossed_up(self, hist: pd.Series) -> bool:
        """True if MACD histogram just turned positive (crossover up)."""
        if len(hist) < 2:
            return False
        return float(hist.iloc[-2]) < 0 and float(hist.iloc[-1]) > 0

    def _hist_crossed_down(self, hist: pd.Series) -> bool:
        """True if MACD histogram just turned negative (crossover down)."""
        if len(hist) < 2:
            return False
        return float(hist.iloc[-2]) > 0 and float(hist.iloc[-1]) < 0

    def _ribbon_strength(self, fast_val: float, slow_val: float,
                         price: float) -> float:
        """
        EMA separation as a fraction of price, normalised to 0.0–1.0.
        0.2% gap → ~0.0 (weak trend / chop boundary)
        1.0% gap → ~1.0 (strong trend)
        """
        if price == 0:
            return 0.0
        gap_pct = abs(fast_val - slow_val) / price
        # Scale: map [MIN_RIBBON, MIN_RIBBON*5] → [0.0, 1.0]
        normalized = (gap_pct - MIN_RIBBON) / (MIN_RIBBON * 4)
        return max(0.0, min(1.0, normalized))

    # ── Core ──────────────────────────────────────────────────────────────────

    def generate_signals(self, all_bars: dict) -> list[dict]:
        """
        all_bars: {symbol: pd.DataFrame with 5Min OHLCV}
        Returns list of signal dicts.
        """
        signals = []
        in_window = self._in_trading_window()

        for symbol, bars in all_bars.items():
            # ── Guard: need enough bars ───────────────────────────────────────
            min_bars = MACD_SLOW + MACD_SIG + 5
            if bars is None or len(bars) < min_bars:
                self.log.warning(
                    f"{symbol}: need {min_bars} bars, got "
                    f"{len(bars) if bars is not None else 0}"
                )
                continue

            close = bars["close"]

            # ── Indicators ────────────────────────────────────────────────────
            ema_fast   = ema(close, EMA_FAST)
            ema_slow   = ema(close, EMA_SLOW)
            _, _, hist = macd(close, MACD_FAST, MACD_SLOW, MACD_SIG)

            cur_price    = float(close.iloc[-1])
            cur_ema_fast = float(ema_fast.iloc[-1])
            cur_ema_slow = float(ema_slow.iloc[-1])

            # Ribbon direction and gap
            ribbon_up    = cur_ema_fast > cur_ema_slow
            ribbon_gap   = abs(cur_ema_fast - cur_ema_slow) / cur_price
            ribbon_ok    = ribbon_gap >= MIN_RIBBON   # enough separation = trending
            strength     = self._ribbon_strength(cur_ema_fast, cur_ema_slow, cur_price)

            # MACD histogram flip
            hist_up   = self._hist_crossed_up(hist)
            hist_down = self._hist_crossed_down(hist)

            # ── BUY conditions ────────────────────────────────────────────────
            if (
                in_window
                and ribbon_up               # EMAs say uptrend
                and ribbon_ok               # ribbon wide enough (not choppy)
                and hist_up                 # MACD just turned positive
                and cur_price > cur_ema_fast  # price confirming above ribbon
            ):
                signals.append({
                    "symbol":   symbol,
                    "signal":   "buy",
                    "strength": round(strength, 2),
                    "reason": (
                        f"EMA{EMA_FAST} {cur_ema_fast:.2f} > "
                        f"EMA{EMA_SLOW} {cur_ema_slow:.2f} | "
                        f"MACD hist crossed up | "
                        f"ribbon={ribbon_gap*100:.2f}%"
                    ),
                    "price":    round(cur_price, 2),
                    "ema_fast": round(cur_ema_fast, 2),
                    "ema_slow": round(cur_ema_slow, 2),
                    "ribbon_pct": round(ribbon_gap * 100, 2),
                })
                self.log.info(f"BUY  {symbol} | {signals[-1]['reason']}")

            # ── SELL conditions ───────────────────────────────────────────────
            elif hist_down or cur_price < cur_ema_fast:
                reason_parts = []
                if hist_down:
                    reason_parts.append("MACD hist crossed down")
                if cur_price < cur_ema_fast:
                    reason_parts.append(
                        f"Price {cur_price:.2f} broke below "
                        f"EMA{EMA_FAST} {cur_ema_fast:.2f}"
                    )

                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": 1.0,
                    "reason":   " | ".join(reason_parts),
                    "price":    round(cur_price, 2),
                    "ema_fast": round(cur_ema_fast, 2),
                    "ema_slow": round(cur_ema_slow, 2),
                })
                self.log.info(f"SELL {symbol} | {signals[-1]['reason']}")

            # ── HOLD ─────────────────────────────────────────────────────────
            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason": (
                        f"EMA{EMA_FAST} {cur_ema_fast:.2f} | "
                        f"EMA{EMA_SLOW} {cur_ema_slow:.2f} | "
                        f"ribbon={'up' if ribbon_up else 'down'} "
                        f"{'ok' if ribbon_ok else '(choppy)'}"
                        + ("" if in_window else " [outside window]")
                    ),
                    "price":    round(cur_price, 2),
                })

        return signals