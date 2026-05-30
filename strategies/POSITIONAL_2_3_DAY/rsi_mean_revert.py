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
from utils.indicators import rsi, sma
import config


class RSIMeanRevert(BaseStrategy):
    def __init__(self):
        super().__init__("RSI Mean Reversion")
        self.period     = config.RSI_PERIOD
        self.oversold   = config.RSI_OVERSOLD
        self.overbought = config.RSI_OVERBOUGHT
        self.log.info(
            f"RSI MR: period={self.period}, "
            f"oversold={self.oversold}, overbought={self.overbought}"
        )

    def generate_signals(self, all_bars: dict) -> list[dict]:
        signals = []

        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < self.period + 10:
                continue

            close    = bars["close"]
            rsi_vals = rsi(close, self.period)
            curr_rsi = rsi_vals.iloc[-1]
            prev_rsi = rsi_vals.iloc[-2]
            price    = close.iloc[-1]

            # BUY: RSI was below oversold and is now recovering
            if prev_rsi < self.oversold and curr_rsi >= self.oversold:
                strength = min(1.0, (self.oversold - prev_rsi) / 20)
                signals.append({
                    "symbol":   symbol,
                    "signal":   "buy",
                    "strength": round(strength, 2),
                    "reason":   f"RSI recovered from oversold ({prev_rsi:.1f} → {curr_rsi:.1f})",
                    "rsi":      round(curr_rsi, 2),
                    "price":    round(price, 2),
                })
                self.log.info(f"BUY signal: {symbol} RSI={curr_rsi:.1f}")

            # SELL: RSI was above overbought and is now falling
            elif prev_rsi > self.overbought and curr_rsi <= self.overbought:
                strength = min(1.0, (prev_rsi - self.overbought) / 20)
                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": round(strength, 2),
                    "reason":   f"RSI fell from overbought ({prev_rsi:.1f} → {curr_rsi:.1f})",
                    "rsi":      round(curr_rsi, 2),
                    "price":    round(price, 2),
                })
                self.log.info(f"SELL signal: {symbol} RSI={curr_rsi:.1f}")

            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   f"RSI neutral at {curr_rsi:.1f}",
                    "rsi":      round(curr_rsi, 2),
                    "price":    round(price, 2),
                })

        return signals