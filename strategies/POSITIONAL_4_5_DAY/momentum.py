"""
strategies/momentum.py — Price Momentum

HOW IT WORKS:
  "Winners keep winning, losers keep losing."

  Measure how much a stock has moved over the last N days.
  - BUY  stocks with strong positive momentum (e.g. +5% over 20 days)
    AND where price is above its 50-day SMA (confirming uptrend)
  - SELL when momentum reverses negative
    OR when price drops below the 50-day SMA

BEST FOR: Strong trending markets. Bad in mean-reverting/choppy markets.

PARAMETERS (set in config.py):
  MOMENTUM_LOOKBACK   = 20   # days
  MOMENTUM_THRESHOLD  = 0.05 # require 5% gain
"""

import pandas as pd
from strategies.base import BaseStrategy
from utils.indicators import momentum, sma, rsi
import config


class MomentumStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("Momentum")
        self.lookback  = config.MOMENTUM_LOOKBACK
        self.threshold = config.MOMENTUM_THRESHOLD
        self.log.info(f"Momentum: lookback={self.lookback}, threshold={self.threshold:.0%}")

    def generate_signals(self, all_bars: dict) -> list[dict]:
        signals = []

        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < max(self.lookback, 50) + 5:
                continue

            close     = bars["close"]
            mom       = momentum(close, self.lookback)
            sma50     = sma(close, 50)
            curr_mom  = mom.iloc[-1]
            price     = close.iloc[-1]
            above_sma = price > sma50.iloc[-1]

            # BUY: strong positive momentum + price above 50-day SMA
            if curr_mom >= self.threshold and above_sma:
                strength = min(1.0, curr_mom / (self.threshold * 3))
                signals.append({
                    "symbol":   symbol,
                    "signal":   "buy",
                    "strength": round(strength, 2),
                    "reason":   f"Momentum {curr_mom:.1%} over {self.lookback}d, "
                                f"price above SMA50 ({sma50.iloc[-1]:.2f})",
                    "momentum": round(curr_mom, 4),
                    "sma50":    round(sma50.iloc[-1], 2),
                    "price":    round(price, 2),
                })
                self.log.info(f"BUY signal: {symbol} momentum={curr_mom:.1%}")

            # SELL: momentum turned negative OR price fell below SMA50
            elif curr_mom < 0 or not above_sma:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": 0.5,
                    "reason":   (
                        f"Momentum negative ({curr_mom:.1%})"
                        if curr_mom < 0
                        else f"Price ({price:.2f}) below SMA50 ({sma50.iloc[-1]:.2f})"
                    ),
                    "momentum": round(curr_mom, 4),
                    "sma50":    round(sma50.iloc[-1], 2),
                    "price":    round(price, 2),
                })
                self.log.info(f"SELL signal: {symbol} momentum={curr_mom:.1%}")

            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   f"Momentum {curr_mom:.1%} below threshold {self.threshold:.1%}",
                    "momentum": round(curr_mom, 4),
                    "sma50":    round(sma50.iloc[-1], 2),
                    "price":    round(price, 2),
                })

        return signals