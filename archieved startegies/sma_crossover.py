"""
strategies/sma_crossover.py — Simple Moving Average Crossover

HOW IT WORKS:
  - Calculate a FAST SMA (e.g. 9-day) and SLOW SMA (e.g. 21-day)
  - BUY  when fast crosses ABOVE slow (momentum starting upward)
  - SELL when fast crosses BELOW slow (momentum starting downward)

BEST FOR: Trending markets. Will have whipsaws in choppy/sideways markets.

PARAMETERS (set in config.py):
  SMA_FAST_PERIOD  = 9
  SMA_SLOW_PERIOD  = 21
"""

import pandas as pd
from strategies.base import BaseStrategy
from utils.indicators import sma, crossover, crossunder
import config


class SMAcrossover(BaseStrategy):
    def __init__(self):
        super().__init__("SMA Crossover")
        self.fast = config.SMA_FAST_PERIOD
        self.slow = config.SMA_SLOW_PERIOD
        self.log.info(f"SMA Crossover: fast={self.fast}, slow={self.slow}")

    def generate_signals(self, all_bars: dict) -> list[dict]:
        """
        all_bars: {symbol: pd.DataFrame with OHLCV columns}
        Returns list of signal dicts.
        """
        signals = []

        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < self.slow + 5:
                self.log.warning(f"{symbol}: not enough bars ({len(bars) if bars is not None else 0})")
                continue

            close = bars["close"]
            fast_sma = sma(close, self.fast)
            slow_sma = sma(close, self.slow)

            # Get the last two rows for signal detection
            buy_signal  = crossover(fast_sma, slow_sma).iloc[-1]
            sell_signal = crossunder(fast_sma, slow_sma).iloc[-1]

            if buy_signal:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "buy",
                    "strength": 0.7,
                    "reason":   f"SMA{self.fast} ({fast_sma.iloc[-1]:.2f}) crossed above "
                                f"SMA{self.slow} ({slow_sma.iloc[-1]:.2f})",
                    "fast_sma": round(fast_sma.iloc[-1], 2),
                    "slow_sma": round(slow_sma.iloc[-1], 2),
                    "price":    round(close.iloc[-1], 2),
                })
                self.log.info(f"BUY signal: {symbol} | {signals[-1]['reason']}")

            elif sell_signal:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": 0.7,
                    "reason":   f"SMA{self.fast} ({fast_sma.iloc[-1]:.2f}) crossed below "
                                f"SMA{self.slow} ({slow_sma.iloc[-1]:.2f})",
                    "fast_sma": round(fast_sma.iloc[-1], 2),
                    "slow_sma": round(slow_sma.iloc[-1], 2),
                    "price":    round(close.iloc[-1], 2),
                })
                self.log.info(f"SELL signal: {symbol} | {signals[-1]['reason']}")

            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   "No crossover detected",
                    "fast_sma": round(fast_sma.iloc[-1], 2),
                    "slow_sma": round(slow_sma.iloc[-1], 2),
                    "price":    round(close.iloc[-1], 2),
                })

        return signals