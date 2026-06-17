"""
strategies/rsi_mean_revert.py — RSI Mean Reversion

HOW IT WORKS:
  RSI (Relative Strength Index) measures if a stock is
  "overbought" or "oversold" on a scale of 0–100.

  - BUY  when RSI falls below OVERSOLD level (e.g. 30)
    → Price dropped too fast, likely to bounce back
  - SELL when RSI rises above OVERBOUGHT level (e.g. 70)
    → Price rose too fast, likely to pull back

BEST FOR: Ranging/sideways markets. Struggles in strong trends.

PARAMETERS (set in config.py):
  RSI_PERIOD     = 14
  RSI_OVERSOLD   = 30
  RSI_OVERBOUGHT = 70
"""

import pandas as pd
from strategies.base import BaseStrategy
from utils.indicators import rsi, sma, bollinger_bands, adx
import config


RSI_BB_PERIOD  = getattr(config, "RSI_BB_PERIOD",     20)
RSI_BB_STD     = getattr(config, "RSI_BB_STD",        2.0)
RSI_ADX_PERIOD = getattr(config, "RSI_ADX_PERIOD",    14)
RSI_ADX_TREND  = getattr(config, "RSI_ADX_TREND",     25)  # above → use extreme 20/80 levels
RSI_MAX_DAYS   = getattr(config, "RSI_MAX_HOLD_DAYS",  2)  # force exit if no bounce


class RSIMeanRevert(BaseStrategy):
    def __init__(self):
        super().__init__("RSI Mean Reversion")
        self.period     = config.RSI_PERIOD
        self.oversold   = config.RSI_OVERSOLD
        self.overbought = config.RSI_OVERBOUGHT
        self._entry_bar: dict[str, int] = {}
        self._bar_cnt:   dict[str, int] = {}
        self.log.info(
            f"RSI MR: period={self.period}, "
            f"oversold={self.oversold}, overbought={self.overbought} | "
            f"BB({RSI_BB_PERIOD},{RSI_BB_STD}) | "
            f"dynamic levels ADX>{RSI_ADX_TREND}→20/80 | max_hold={RSI_MAX_DAYS}d"
        )

    def generate_signals(self, all_bars: dict) -> list[dict]:
        signals = []

        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < max(self.period, RSI_BB_PERIOD, RSI_ADX_PERIOD) + 10:
                continue

            close    = bars["close"]
            high     = bars["high"]
            low      = bars["low"]
            rsi_vals = rsi(close, self.period)
            bb_upper, _, bb_lower = bollinger_bands(close, RSI_BB_PERIOD, RSI_BB_STD)
            adx_vals = adx(high, low, close, RSI_ADX_PERIOD)

            curr_rsi    = float(rsi_vals.iloc[-1])
            prev_rsi    = float(rsi_vals.iloc[-2])
            curr_adx    = float(adx_vals.iloc[-1])
            price       = float(close.iloc[-1])
            at_bb_lower = price <= float(bb_lower.iloc[-1])
            at_bb_upper = price >= float(bb_upper.iloc[-1])

            # Dynamic levels: strong trend → need extreme exhaustion (20/80)
            #                 ranging     → standard levels (config oversold/overbought)
            trending  = curr_adx > RSI_ADX_TREND
            os_level  = 20 if trending else self.oversold
            ob_level  = 80 if trending else self.overbought

            # Time-based exit: sell if held > RSI_MAX_DAYS without a bounce
            self._bar_cnt[symbol] = self._bar_cnt.get(symbol, 0) + 1
            bars_held  = self._bar_cnt[symbol] - self._entry_bar.get(
                symbol, self._bar_cnt[symbol])
            force_exit = symbol in self._entry_bar and bars_held >= RSI_MAX_DAYS

            if force_exit:
                self._entry_bar.pop(symbol, None)
                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": 0.5,
                    "reason":   f"Force exit: {bars_held}d held, no bounce (>{RSI_MAX_DAYS}d)",
                    "rsi":      round(curr_rsi, 2),
                    "price":    round(price, 2),
                })
                self.log.info(f"FORCE-EXIT {symbol} | {bars_held}d no bounce")

            # BUY: RSI crossed back above oversold level AND BB lower confirms
            elif prev_rsi < os_level and curr_rsi >= os_level and at_bb_lower:
                strength = min(1.0, (os_level - prev_rsi) / 20)
                self._entry_bar[symbol] = self._bar_cnt[symbol]
                signals.append({
                    "symbol":   symbol,
                    "signal":   "buy",
                    "strength": round(strength, 2),
                    "reason":   (f"RSI {prev_rsi:.1f}→{curr_rsi:.1f} (lvl={os_level}) | "
                                 f"BB lower touch | ADX {curr_adx:.1f} "
                                 f"({'trending' if trending else 'ranging'})"),
                    "rsi":      round(curr_rsi, 2),
                    "price":    round(price, 2),
                    "adx":      round(curr_adx, 1),
                    "bb_lower": round(float(bb_lower.iloc[-1]), 2),
                })
                self.log.info(f"BUY signal: {symbol} RSI={curr_rsi:.1f} lvl={os_level}")

            # SELL: RSI crossed back below overbought AND BB upper confirms
            elif prev_rsi > ob_level and curr_rsi <= ob_level and at_bb_upper:
                strength = min(1.0, (prev_rsi - ob_level) / 20)
                self._entry_bar.pop(symbol, None)
                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": round(strength, 2),
                    "reason":   (f"RSI {prev_rsi:.1f}→{curr_rsi:.1f} (lvl={ob_level}) | "
                                 f"BB upper touch | ADX {curr_adx:.1f}"),
                    "rsi":      round(curr_rsi, 2),
                    "price":    round(price, 2),
                    "adx":      round(curr_adx, 1),
                })
                self.log.info(f"SELL signal: {symbol} RSI={curr_rsi:.1f} lvl={ob_level}")

            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   (f"RSI {curr_rsi:.1f} | ADX {curr_adx:.1f} "
                                 f"({'trending' if trending else 'ranging'}) | "
                                 f"levels={os_level}/{ob_level}"),
                    "rsi":      round(curr_rsi, 2),
                    "price":    round(price, 2),
                })

        return signals