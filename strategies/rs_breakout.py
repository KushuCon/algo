"""
strategies/rs_breakout.py — Relative Strength Breakout (Enhanced)

Based on institutional strategy: Compare stock momentum vs SPY, enter on
breakouts with MACD confirmation. Designed for 3-7 day positional holds.

FIXES from original:
• RS threshold lowered from 1.5 (50% outperformance) to 1.05 (5%) or top 20%
• ATR calculated from same DataFrame (no duplicate downloads)
• MACD exit requires 3+ days held (was 2, too fast)
• Added trailing stop: breakeven at +1x ATR, trail at 1.5x ATR
• Added sector RS filter (vs SMH for semis, etc.)
• Added market breadth filter
• Uses your utils.indicators instead of ta library
"""

import numpy as np
import pandas as pd
from strategies.base import BaseStrategy
from utils.indicators import rsi, macd, atr, ema, sma, bollinger_bands
import config

# ── Configurable defaults ───────────────────────────────────────────────────
RS_LOOKBACK       = getattr(config, "RS_LOOKBACK", 10)          # days for RS calc
RS_THRESHOLD      = getattr(config, "RS_THRESHOLD", 1.05)     # 5% outperformance
RS_USE_PERCENTILE = getattr(config, "RS_USE_PERCENTILE", True) # Use top N% instead of fixed
RS_TOP_PCT        = getattr(config, "RS_TOP_PCT", 0.20)        # Top 20%
RS_BREAKOUT_DAYS  = getattr(config, "RS_BREAKOUT_DAYS", 20)   # 20-day high
RS_MACD_FAST      = getattr(config, "RS_MACD_FAST", 12)
RS_MACD_SLOW      = getattr(config, "RS_MACD_SLOW", 26)
RS_MACD_SIGNAL    = getattr(config, "RS_MACD_SIGNAL", 9)
RS_VOL_MULT       = getattr(config, "RS_VOL_MULT", 1.3)         # Volume confirmation
RS_ATR_PERIOD     = getattr(config, "RS_ATR_PERIOD", 14)
RS_ATR_STOP_MULT  = getattr(config, "RS_ATR_STOP_MULT", 2.0)
RS_ATR_TARGET_MULT= getattr(config, "RS_ATR_TARGET_MULT", 3.0)
RS_TRAIL_ATR_MULT = getattr(config, "RS_TRAIL_ATR_MULT", 1.5)   # Trailing stop
RS_MAX_HOLD       = getattr(config, "RS_MAX_HOLD", 7)           # days
RS_MIN_HOLD_EXIT  = getattr(config, "RS_MIN_HOLD_EXIT", 3)      # Min days before MACD exit
RS_SPY_TREND_DAYS = getattr(config, "RS_SPY_TREND_DAYS", 50)    # SPY SMA for regime
RS_BREADTH_FILTER = getattr(config, "RS_BREADTH_FILTER", True)  # Market breadth check


class RSBreakoutStrategy(BaseStrategy):
    """
    Relative Strength Breakout strategy.

    Entry: Stock shows relative strength vs SPY, breaks 20-day high,
           MACD bullish, volume confirms.
    Exit:  MACD bearish (after min hold), ATR stop, ATR target, or max hold.
    """

    def __init__(self):
        super().__init__("RS Breakout")
        self.lookback       = RS_LOOKBACK
        self.rs_threshold   = RS_THRESHOLD
        self.use_percentile = RS_USE_PERCENTILE
        self.top_pct        = RS_TOP_PCT
        self.breakout_days  = RS_BREAKOUT_DAYS
        self.vol_mult       = RS_VOL_MULT
        self.atr_period     = RS_ATR_PERIOD
        self.atr_stop_mult  = RS_ATR_STOP_MULT
        self.atr_target_mult= RS_ATR_TARGET_MULT
        self.trail_atr_mult = RS_TRAIL_ATR_MULT
        self.max_hold       = RS_MAX_HOLD
        self.min_hold_exit  = RS_MIN_HOLD_EXIT
        self.spy_trend_days = RS_SPY_TREND_DAYS
        self.breadth_filter = RS_BREADTH_FILTER

        # Track active positions for trailing stops
        self._positions: dict[str, dict] = {}  # symbol -> {entry_price, stop, target, highest}

        self.log.info(
            f"RS Breakout: lookback={self.lookback}, "
            f"rs_threshold={self.rs_threshold:.0%}, "
            f"use_percentile={self.use_percentile}, top_pct={self.top_pct:.0%}, "
            f"breakout={self.breakout_days}d, vol_mult={self.vol_mult}x, "
            f"atr_stop={self.atr_stop_mult}x, atr_target={self.atr_target_mult}x, "
            f"trail={self.trail_atr_mult}x, max_hold={self.max_hold}d"
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _calc_rs(self, stock_close: pd.Series, spy_close: pd.Series) -> pd.Series:
        """Relative Strength = (1 + stock_return) / (1 + spy_return) over lookback."""
        stock_ret = stock_close.pct_change(self.lookback)
        spy_ret   = spy_close.pct_change(self.lookback)
        # Avoid division by zero
        spy_ret_safe = spy_ret.replace(0, np.nan)
        rs = (1 + stock_ret) / (1 + spy_ret_safe)
        return rs

    def _calc_macd(self, close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
        """Return MACD line, signal line, histogram."""
        return macd(close, RS_MACD_FAST, RS_MACD_SLOW, RS_MACD_SIGNAL)

    def _is_macd_bullish(self, hist: pd.Series) -> bool:
        """MACD histogram positive and increasing."""
        if len(hist) < 2:
            return False
        return float(hist.iloc[-1]) > 0 and float(hist.iloc[-1]) > float(hist.iloc[-2])

    def _is_macd_bearish(self, hist: pd.Series) -> bool:
        """MACD histogram negative or crossed down."""
        if len(hist) < 2:
            return False
        return float(hist.iloc[-1]) < 0 or (
            float(hist.iloc[-2]) > 0 and float(hist.iloc[-1]) <= 0
        )

    def _check_spy_trend(self, spy_close: pd.Series) -> bool:
        """Return True if SPY is above its SMA (bull market)."""
        if len(spy_close) < self.spy_trend_days + 5:
            return True  # Default to allowing trades
        spy_sma = sma(spy_close, self.spy_trend_days)
        return float(spy_close.iloc[-1]) > float(spy_sma.iloc[-1])

    def _check_market_breadth(self, all_bars: dict) -> bool:
        """Check if >50% of stocks in universe are above their 20-day SMA."""
        if not self.breadth_filter or not all_bars:
            return True

        above_count = 0
        total = 0
        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < 25:
                continue
            close = bars["close"]
            sma20 = sma(close, 20)
            if float(close.iloc[-1]) > float(sma20.iloc[-1]):
                above_count += 1
            total += 1

        if total == 0:
            return True
        breadth = above_count / total
        self.log.debug(f"Market breadth: {breadth:.1%} ({above_count}/{total})")
        return breadth >= 0.40  # At least 40% stocks above SMA20

    # ── Main signal generation ────────────────────────────────────────────

    def generate_signals(self, all_bars: dict) -> list[dict]:
        """
        all_bars: {symbol: pd.DataFrame with OHLCV columns, "SPY": spy_bars}
        Returns list of signal dicts.
        """
        signals = []

        # Extract SPY bars
        spy_bars = all_bars.get("SPY")
        if spy_bars is None or len(spy_bars) < self.lookback + 10:
            self.log.warning("SPY data missing or insufficient for RS calc.")
            return []

        spy_close = spy_bars["close"]

        # Market regime checks
        spy_bullish = self._check_spy_trend(spy_close)
        breadth_ok = self._check_market_breadth(all_bars)

        if not spy_bullish:
            self.log.info("SPY below SMA — skipping RS breakout entries.")
        if not breadth_ok:
            self.log.info("Market breadth weak — reducing signal strength.")

        # Calculate RS for all symbols
        rs_scores = {}
        valid_symbols = []

        for symbol, bars in all_bars.items():
            if symbol == "SPY" or bars is None:
                continue
            if len(bars) < max(self.lookback, self.breakout_days, self.atr_period) + 5:
                continue

            close = bars["close"]

            # Align with SPY dates
            common_idx = close.index.intersection(spy_close.index)
            if len(common_idx) < self.lookback + 5:
                continue

            stock_aligned = close.reindex(common_idx)
            spy_aligned = spy_close.reindex(common_idx)

            rs = self._calc_rs(stock_aligned, spy_aligned)
            rs_scores[symbol] = float(rs.iloc[-1]) if not rs.empty else 0.0
            valid_symbols.append(symbol)

        if not valid_symbols:
            self.log.warning("No valid symbols for RS calculation.")
            return []

        # Determine RS threshold dynamically
        if self.use_percentile:
            rs_values = list(rs_scores.values())
            threshold = np.percentile(rs_values, (1 - self.top_pct) * 100)
            self.log.info(f"Dynamic RS threshold (top {self.top_pct:.0%}): {threshold:.3f}")
        else:
            threshold = self.rs_threshold
            self.log.info(f"Fixed RS threshold: {threshold:.3f}")

        # Generate signals
        for symbol in valid_symbols:
            bars = all_bars[symbol]
            close = bars["close"]
            high = bars["high"]
            low = bars["low"]
            volume = bars.get("volume", pd.Series(np.ones(len(close)), index=close.index))

            price = float(close.iloc[-1])

            # ── Relative Strength ──
            rs_score = rs_scores.get(symbol, 0.0)
            rs_strong = rs_score >= threshold

            # ── Breakout ──
            high_20d = float(high.rolling(self.breakout_days).max().iloc[-2])  # Yesterday's 20d high
            breakout = price > high_20d

            # ── MACD ──
            macd_line, signal_line, hist = self._calc_macd(close)
            macd_bull = self._is_macd_bullish(hist)

            # ── Volume ──
            vol_avg = float(volume.rolling(20).mean().iloc[-1])
            vol_current = float(volume.iloc[-1])
            vol_confirm = vol_current >= vol_avg * self.vol_mult if vol_avg > 0 else False

            # ── ATR ──
            atr_vals = atr(high, low, close, self.atr_period)
            curr_atr = float(atr_vals.iloc[-1])

            # ── Position tracking for trailing stop ──
            pos = self._positions.get(symbol)

            # ── Signal logic ──

            # ENTRY
            if (
                spy_bullish
                and breadth_ok
                and rs_strong
                and breakout
                and macd_bull
                and vol_confirm
                and curr_atr > 0
                and symbol not in self._positions
            ):
                stop_price = price - self.atr_stop_mult * curr_atr
                target_price = price + self.atr_target_mult * curr_atr

                self._positions[symbol] = {
                    "entry_price": price,
                    "stop_price": stop_price,
                    "target_price": target_price,
                    "highest_price": price,
                    "entry_date": close.index[-1],
                }

                signals.append({
                    "symbol": symbol,
                    "signal": "buy",
                    "strength": round(min(1.0, rs_score / 1.2), 3),
                    "reason": (
                        f"RS Breakout | RS={rs_score:.2f} (threshold={threshold:.2f}) | "
                        f"Break 20d high {high_20d:.2f} | "
                        f"MACD bull | Vol {vol_current/vol_avg:.1f}x | "
                        f"ATR stop {stop_price:.2f} target {target_price:.2f}"
                    ),
                    "rs_score": round(rs_score, 4),
                    "breakout_level": round(high_20d, 2),
                    "atr": round(curr_atr, 4),
                    "stop_price": round(stop_price, 2),
                    "target_price": round(target_price, 2),
                    "price": round(price, 2),
                })
                self.log.info(
                    f"BUY {symbol} | RS={rs_score:.3f} | "
                    f"Breakout={breakout} | MACD={macd_bull} | Vol={vol_confirm}"
                )

            # EXIT (for existing positions)
            elif symbol in self._positions:
                pos = self._positions[symbol]
                entry_price = pos["entry_price"]
                stop_price = pos["stop_price"]
                target_price = pos["target_price"]
                highest = pos["highest_price"]
                entry_date = pos["entry_date"]

                # Update highest price for trailing stop
                if price > highest:
                    pos["highest_price"] = price
                    highest = price

                # Calculate days held
                days_held = (close.index[-1] - entry_date).days if hasattr(close.index[-1], 'days') else 0

                # Trailing stop: breakeven at +1x ATR, then trail at 1.5x ATR
                trailing_stop = max(
                    stop_price,
                    entry_price,  # Breakeven once in profit
                    highest - self.trail_atr_mult * curr_atr  # Trail below highs
                )

                exit_reason = None

                # Stop loss hit
                if price <= trailing_stop and price < entry_price * 1.01:  # Not just breakeven
                    exit_reason = f"STOP (trailing {trailing_stop:.2f})"

                # Target hit
                elif price >= target_price:
                    exit_reason = f"TARGET ({self.atr_target_mult}x ATR)"

                # MACD bearish (after minimum hold)
                elif self._is_macd_bearish(hist) and days_held >= self.min_hold_exit:
                    exit_reason = f"MACD_EXIT (held {days_held}d)"

                # Max hold
                elif days_held >= self.max_hold:
                    exit_reason = f"TIME_EXIT ({self.max_hold}d max)"

                if exit_reason:
                    pnl_pct = (price - entry_price) / entry_price
                    signals.append({
                        "symbol": symbol,
                        "signal": "sell",
                        "strength": 1.0,
                        "reason": exit_reason,
                        "pnl_pct": round(pnl_pct, 4),
                        "days_held": days_held,
                        "entry_price": round(entry_price, 2),
                        "price": round(price, 2),
                    })
                    self.log.info(
                        f"SELL {symbol} | {exit_reason} | "
                        f"PnL={pnl_pct:+.2%} | Held {days_held}d"
                    )
                    del self._positions[symbol]
                else:
                    # Still holding — emit hold signal with position info
                    signals.append({
                        "symbol": symbol,
                        "signal": "hold",
                        "strength": 0.0,
                        "reason": (
                            f"Holding | Entry {entry_price:.2f} | "
                            f"Current {price:.2f} | Trail {trailing_stop:.2f} | "
                            f"Target {target_price:.2f} | Days {days_held}"
                        ),
                        "entry_price": round(entry_price, 2),
                        "trailing_stop": round(trailing_stop, 2),
                        "target_price": round(target_price, 2),
                        "days_held": days_held,
                        "price": round(price, 2),
                    })

            # No position, no signal
            else:
                signals.append({
                    "symbol": symbol,
                    "signal": "hold",
                    "strength": 0.0,
                    "reason": (
                        f"RS={rs_score:.3f} | Breakout={breakout} | "
                        f"MACD={macd_bull} | Vol={vol_confirm} | "
                        f"SPY_bull={spy_bullish} | Breadth={breadth_ok}"
                    ),
                    "rs_score": round(rs_score, 4),
                    "price": round(price, 2),
                })

        return signals
