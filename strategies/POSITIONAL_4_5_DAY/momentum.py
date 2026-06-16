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


MOM_VOL_MULT  = getattr(config, "MOMENTUM_VOL_MULT",  1.5)   # volume spike requirement
MOM_SCALE_PCT = getattr(config, "MOMENTUM_SCALE_PCT", 0.03)  # scale-out at +3%


class MomentumStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("Momentum")
        self.lookback  = getattr(config, "MOMENTUM_LOOKBACK",  10)   # default: 10 (was 20)
        self.threshold = getattr(config, "MOMENTUM_THRESHOLD", 0.05)
        self._entry_price: dict[str, float] = {}  # symbol → entry price for scale-out
        self.log.info(
            f"Momentum: lookback={self.lookback}, threshold={self.threshold:.0%}, "
            f"vol_mult={MOM_VOL_MULT}×, scale_out={MOM_SCALE_PCT:.0%}"
        )

    def generate_signals(self, all_bars: dict) -> list[dict]:
        signals = []

        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < max(self.lookback, 50) + 5:
                continue

            close     = bars["close"]
            volume    = bars["volume"]
            mom       = momentum(close, self.lookback)
            sma50     = sma(close, 50)
            curr_mom  = float(mom.iloc[-1])
            price     = float(close.iloc[-1])
            above_sma = price > float(sma50.iloc[-1])

            # Volume spike: current bar vs 20-bar rolling average
            avg_vol   = float(volume.rolling(20).mean().iloc[-1])
            vol_spike = float(volume.iloc[-1]) >= MOM_VOL_MULT * avg_vol

            # Scale-out: +3% from entry → emit sell_half + move stop to breakeven
            entry      = self._entry_price.get(symbol)
            scale_out  = entry is not None and price >= entry * (1 + MOM_SCALE_PCT)

            if scale_out:
                signals.append({
                    "symbol":             symbol,
                    "signal":             "sell_half",   # PM: close 50% of position
                    "strength":           0.5,
                    "reason":             (f"Scale-out: +{(price/entry - 1):.1%} from "
                                           f"entry {entry:.2f} | stop → breakeven"),
                    "price":              round(price, 2),
                    "entry":              round(entry, 2),
                    "move_stop_to_entry": True,
                })
                self._entry_price.pop(symbol, None)
                self.log.info(f"SCALE-OUT {symbol} | +{(price/entry - 1):.1%}")

            # BUY: strong momentum + above SMA50 + volume spike
            elif curr_mom >= self.threshold and above_sma and vol_spike:
                strength = min(1.0, curr_mom / (self.threshold * 3))
                self._entry_price[symbol] = price
                signals.append({
                    "symbol":   symbol,
                    "signal":   "buy",
                    "strength": round(strength, 2),
                    "reason":   (f"Momentum {curr_mom:.1%} over {self.lookback}d | "
                                 f"SMA50 ok | vol {volume.iloc[-1]/avg_vol:.1f}× avg"),
                    "momentum": round(curr_mom, 4),
                    "sma50":    round(float(sma50.iloc[-1]), 2),
                    "price":    round(price, 2),
                })
                self.log.info(f"BUY signal: {symbol} momentum={curr_mom:.1%}")

            # SELL: momentum turned negative OR price fell below SMA50
            elif curr_mom < 0 or not above_sma:
                self._entry_price.pop(symbol, None)
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
                    "sma50":    round(float(sma50.iloc[-1]), 2),
                    "price":    round(price, 2),
                })
                self.log.info(f"SELL signal: {symbol} momentum={curr_mom:.1%}")

            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   (f"Momentum {curr_mom:.1%} below threshold "
                                 f"{self.threshold:.1%}"
                                 + ("" if vol_spike else " | no volume spike")),
                    "momentum": round(curr_mom, 4),
                    "sma50":    round(float(sma50.iloc[-1]), 2),
                    "price":    round(price, 2),
                })

        return signals

