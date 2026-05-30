
import pandas as pd
from strategies.base import BaseStrategy
from utils.indicators import ema, atr, crossover, crossunder
import config

# fallback defaults if not in config
MA_FAST    = getattr(config, "MA_FAST_PERIOD",    12)
MA_SLOW    = getattr(config, "MA_SLOW_PERIOD",    26)
MA_ATR_P   = getattr(config, "MA_ATR_PERIOD",     14)
MA_ATR_M   = getattr(config, "MA_ATR_MULT",       2.0)
MA_RISK    = getattr(config, "MA_RISK_PER_TRADE", 0.01)


class MACrossoverWithSL(BaseStrategy):
    def __init__(self):
        super().__init__("MA Crossover + SL + Sizing")
        self.fast     = MA_FAST
        self.slow     = MA_SLOW
        self.atr_p    = MA_ATR_P
        self.atr_mult = MA_ATR_M
        self.risk_pct = MA_RISK
        self.log.info(
            f"MA Crossover SL: fast={self.fast}, slow={self.slow}, "
            f"atr={self.atr_p}×{self.atr_mult}, risk={self.risk_pct:.1%}"
        )

    def generate_signals(self, all_bars: dict) -> list[dict]:
        signals = []

        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < self.slow + self.atr_p + 5:
                continue

            close = bars["close"]
            high  = bars["high"]
            low   = bars["low"]

            fast_ema = ema(close, self.fast)
            slow_ema = ema(close, self.slow)
            atr_vals = atr(high, low, close, self.atr_p)

            curr_atr   = float(atr_vals.iloc[-1])
            curr_price = float(close.iloc[-1])
            stop_dist  = self.atr_mult * curr_atr

            buy_cross  = crossover(fast_ema, slow_ema).iloc[-1]
            sell_cross = crossunder(fast_ema, slow_ema).iloc[-1]

            # Position size: risk 1% of portfolio / stop distance in shares
            # strength encodes how many shares relative to max position
            # (portfolio manager will scale by MAX_POSITION_PCT)
            size_strength = min(1.0, self.risk_pct / (stop_dist / curr_price + 1e-9))

            if buy_cross:
                signals.append({
                    "symbol":    symbol,
                    "signal":    "buy",
                    "strength":  round(size_strength, 3),
                    "reason":    (f"EMA{self.fast} crossed above EMA{self.slow} | "
                                  f"ATR stop at {curr_price - stop_dist:.2f} "
                                  f"({self.atr_mult}×ATR={curr_atr:.2f})"),
                    "fast_ema":  round(float(fast_ema.iloc[-1]), 2),
                    "slow_ema":  round(float(slow_ema.iloc[-1]), 2),
                    "atr":       round(curr_atr, 4),
                    "stop_price": round(curr_price - stop_dist, 2),
                    "price":     round(curr_price, 2),
                })
                self.log.info(f"BUY: {symbol} | strength={size_strength:.2f}")

            elif sell_cross:
                signals.append({
                    "symbol":    symbol,
                    "signal":    "sell",
                    "strength":  0.5,
                    "reason":    (f"EMA{self.fast} crossed below EMA{self.slow}"),
                    "fast_ema":  round(float(fast_ema.iloc[-1]), 2),
                    "slow_ema":  round(float(slow_ema.iloc[-1]), 2),
                    "atr":       round(curr_atr, 4),
                    "price":     round(curr_price, 2),
                })
                self.log.info(f"SELL: {symbol} | MA crossunder")

            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   "No crossover",
                    "price":    round(curr_price, 2),
                })

        return signals
