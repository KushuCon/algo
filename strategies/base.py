"""
strategies/base.py — Abstract base class for all strategies.
Every strategy must implement generate_signals().
"""

from abc import ABC, abstractmethod
import pandas as pd
from utils.logger import get_logger


class BaseStrategy(ABC):
    """
    All trading strategies inherit from this.

    Subclasses implement generate_signals(bars) which returns a
    DataFrame with columns:
      symbol   — ticker
      signal   — "buy" | "sell" | "hold"
      strength — float 0.0–1.0 (optional, for position sizing)
      reason   — human-readable explanation string
    """

    def __init__(self, name: str):
        self.name = name
        self.log  = get_logger(f"strategy.{name}")

    @abstractmethod
    def generate_signals(self, bars: pd.DataFrame) -> list[dict]:
        """
        Given OHLCV bars, return a list of signal dicts:
        [
          {
            "symbol":   "AAPL",
            "signal":   "buy",     # or "sell" or "hold"
            "strength": 0.8,       # 0.0-1.0, used for position sizing
            "reason":   "Fast SMA crossed above slow SMA",
          },
          ...
        ]
        """
        raise NotImplementedError

    def __repr__(self):
        return f"<Strategy: {self.name}>"