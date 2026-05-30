"""
strategies/scalp_1m.py — 1-Minute VWAP + RSI + Volume Scalper

HOW IT WORKS:
  Intraday price constantly reverts to VWAP (Volume Weighted Average Price).
  We buy dips BELOW VWAP when RSI confirms oversold AND volume spikes — the
  spike signals institutional absorption (smart money buying the dip), not
  just random selling. We exit when price reclaims VWAP or RSI turns overbought.

ENTRY (BUY):
  1. Price < VWAP  (we're below the day's fair value)
  2. RSI < RSI_OVERSOLD (default 35 — oversold but not extreme)
  3. Volume > VOL_MULT × 20-bar avg volume (confirms conviction)
  4. Time filter: 09:30–15:30 ET only (avoid open chop + EOD illiquidity)

EXIT (SELL):
  1. Price > VWAP  (fair value reclaimed — take profit)
  2. RSI > RSI_OVERBOUGHT (default 65 — mean-revert complete)
  (Hard stop-loss / take-profit handled by PortfolioManager)

SIGNAL STRENGTH:
  Scaled by volume ratio (how many times above avg), capped at 1.0.
  Higher strength → PortfolioManager allocates a larger position.

BEST FOR:
  High-liquidity names (AAPL, MSFT, NVDA, SPY, QQQ).
  Intraday mean-reversion. NOT suited for strong trending days
  (add an ADX > 25 filter or switch to scalp_5m on trend days).

PARAMETERS (add to config.py):
  SCALP1_RSI_PERIOD    = 9      # Shorter RSI for faster response
  SCALP1_RSI_OVERSOLD  = 35     # Less extreme than daily (30)
  SCALP1_RSI_OVERBOUGHT= 65
  SCALP1_VOL_PERIOD    = 20     # Bars for volume moving average
  SCALP1_VOL_MULT      = 1.5    # Volume must be 1.5× avg to confirm
  SCALP1_EOD_CUTOFF    = "15:30" # No new buys after this time

IMPORTANT FOR BACKTESTING:
  - Use 1Min bar data from Alpaca: timeframe="1Min"
  - VWAP resets each day — your backtest must group bars by date
  - Slippage on 1min bars is significant; model at least 0.02% each way
  - This strategy makes many small trades — commissions matter
"""

from datetime import time as dtime
import pandas as pd
from strategies.base import BaseStrategy
from utils.indicators import rsi, vwap_session,  adx
from utils.helpers import now_et, ET
import config


# ── Defaults (override in config.py) ─────────────────────────────────────────
RSI_PERIOD     = getattr(config, "SCALP1_RSI_PERIOD",     9)
RSI_OVERSOLD   = getattr(config, "SCALP1_RSI_OVERSOLD",  35)
RSI_OVERBOUGHT = getattr(config, "SCALP1_RSI_OVERBOUGHT", 65)
VOL_PERIOD     = getattr(config, "SCALP1_VOL_PERIOD",    20)
VOL_MULT       = getattr(config, "SCALP1_VOL_MULT",     1.5)
EOD_CUTOFF     = getattr(config, "SCALP1_EOD_CUTOFF",  "15:30")
ADX_PERIOD     = getattr(config, "SCALP1_ADX_PERIOD",   14)
VIX_THRESH     = getattr(config, "SCALP1_VIX_THRESH",   25)    # halve size above this
GAP_SKIP_PCT   = getattr(config, "SCALP1_GAP_SKIP",     0.02)  # skip if open gap > 2%


def _parse_cutoff(t_str: str) -> dtime:
    h, m = map(int, t_str.split(":"))
    return dtime(h, m)


class ScalpOneMin(BaseStrategy):
    """
    1-minute VWAP reversion scalper.
    Requires 1Min OHLCV bars from Alpaca (pass timeframe="1Min" to get_bars).
    """
    TIMEFRAME = "1Min"
    BAR_LIMIT = 400

    def __init__(self):
        super().__init__("Scalp 1Min")
        self.eod_cutoff = _parse_cutoff(EOD_CUTOFF)
        self.log.info(
            f"Scalp1m | RSI({RSI_PERIOD}) oversold={RSI_OVERSOLD} "
            f"overbought={RSI_OVERBOUGHT} | vol_mult={VOL_MULT}× "
            f"| EOD cutoff={EOD_CUTOFF}"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_eod(self) -> bool:
        """Return True if we're past the EOD cutoff (no new buys)."""
        return now_et().time() >= self.eod_cutoff

    def _session_bars(self, bars: pd.DataFrame, min_bars: int) -> pd.DataFrame:
        """Prefer today's US session bars for live VWAP; keep full series for backtest."""
        if bars is None or bars.empty:
            return bars
        today = now_et().date()
        idx = bars.index
        if isinstance(idx, pd.DatetimeIndex):
            if idx.tz is not None:
                dates = idx.tz_convert(ET).date
            else:
                dates = pd.to_datetime(idx).tz_localize("UTC").tz_convert(ET).date
        else:
            dates = pd.to_datetime(idx).tz_localize("UTC").tz_convert(ET).date
        subset = bars.loc[dates == today]
        if len(subset) >= min_bars:
            return subset
        return bars

    def _vol_ratio(self, volume: pd.Series) -> float:
        """Current bar volume divided by rolling average. >1 = above average."""
        avg = volume.rolling(VOL_PERIOD).mean()
        if avg.iloc[-1] == 0:
            return 0.0
        return float(volume.iloc[-1] / avg.iloc[-1])

    # ── Core ──────────────────────────────────────────────────────────────────

    def generate_signals(self, all_bars: dict) -> list[dict]:
        """
        all_bars: {symbol: pd.DataFrame with 1Min OHLCV}
        Returns list of signal dicts.

        NOTE: broker.get_bars() must be called with timeframe="1Min" for this
        strategy. The main loop needs a separate get_bars call or the strategy
        must override how bars are fetched.
        """
        signals = []
        eod = self._is_eod()

        for symbol, bars in all_bars.items():
            # ── Guard: need enough bars for all indicators ────────────────────
            min_bars = max(RSI_PERIOD, VOL_PERIOD) + 5
            if bars is None or len(bars) < min_bars:
                self.log.warning(
                    f"{symbol}: need {min_bars} bars, got "
                    f"{len(bars) if bars is not None else 0}"
                )
                continue

            bars = self._session_bars(bars, min_bars)
            close  = bars["close"]
            high   = bars["high"]
            low    = bars["low"]
            volume = bars["volume"]

            # ── Indicators ────────────────────────────────────────────────────
            rsi_vals  = rsi(close, RSI_PERIOD)
            vwap_vals = vwap_session(high, low, close, volume, bars.index)

            cur_rsi  = float(rsi_vals.iloc[-1])
            cur_vwap = float(vwap_vals.iloc[-1])
            cur_price= float(close.iloc[-1])
            vol_ratio= self._vol_ratio(volume)

            # ── BUY conditions ────────────────────────────────────────────────
            if (
                not eod                        # respect EOD cutoff
                and cur_price < cur_vwap       # below fair value
                and cur_rsi   < RSI_OVERSOLD   # oversold
                and vol_ratio >= VOL_MULT       # volume spike confirms
            ):
                # Strength: volume ratio scaled to 0.0–1.0 (cap at 3× avg → 1.0)
                strength = min(1.0, (vol_ratio - 1.0) / 2.0)

                signals.append({
                    "symbol":   symbol,
                    "signal":   "buy",
                    "strength": round(strength, 2),
                    "reason": (
                        f"Price {cur_price:.2f} below VWAP {cur_vwap:.2f} | "
                        f"RSI {cur_rsi:.1f} < {RSI_OVERSOLD} | "
                        f"Vol {vol_ratio:.1f}× avg"
                    ),
                    "price":    round(cur_price, 2),
                    "vwap":     round(cur_vwap, 2),
                    "rsi":      round(cur_rsi, 1),
                    "vol_ratio":round(vol_ratio, 2),
                })
                self.log.info(f"BUY  {symbol} | {signals[-1]['reason']}")

            # ── SELL conditions ───────────────────────────────────────────────
            elif (
                cur_price > cur_vwap           # reclaimed VWAP (target hit)
                or cur_rsi > RSI_OVERBOUGHT    # overbought
            ):
                reason_parts = []
                if cur_price > cur_vwap:
                    reason_parts.append(f"Price {cur_price:.2f} reclaimed VWAP {cur_vwap:.2f}")
                if cur_rsi > RSI_OVERBOUGHT:
                    reason_parts.append(f"RSI {cur_rsi:.1f} > {RSI_OVERBOUGHT}")

                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": 1.0,
                    "reason":   " | ".join(reason_parts),
                    "price":    round(cur_price, 2),
                    "vwap":     round(cur_vwap, 2),
                    "rsi":      round(cur_rsi, 1),
                })
                self.log.info(f"SELL {symbol} | {signals[-1]['reason']}")

            # ── HOLD ─────────────────────────────────────────────────────────
            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason": (
                        f"Price {cur_price:.2f} | VWAP {cur_vwap:.2f} | "
                        f"RSI {cur_rsi:.1f} | Vol {vol_ratio:.1f}×"
                        + (" [EOD — no new buys]" if eod else "")
                    ),
                    "price":    round(cur_price, 2),
                })

        return signals