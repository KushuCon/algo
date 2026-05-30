
import pandas as pd
from strategies.base import BaseStrategy
from utils.indicators import ema, atr, rsi, sma, crossover, crossunder
import config

# fallback defaults if not in config
MA_FAST    = getattr(config, "MA_FAST_PERIOD",    12)
MA_SLOW    = getattr(config, "MA_SLOW_PERIOD",    26)
MA_ATR_P   = getattr(config, "MA_ATR_PERIOD",     14)
MA_ATR_M   = getattr(config, "MA_ATR_MULT",       2.0)
MA_RISK    = getattr(config, "MA_RISK_PER_TRADE", 0.01)
MA_RSI_P   = getattr(config, "MA_RSI_PERIOD",     14)
MA_RSI_CAP = getattr(config, "MA_RSI_OVERBOUGHT", 65)
MA_MAX_DAYS= getattr(config, "MA_MAX_HOLD_DAYS",   3)


class MACrossoverWithSL(BaseStrategy):
    def __init__(self):
        super().__init__("MA Crossover + SL + Sizing")
        self.fast     = MA_FAST
        self.slow     = MA_SLOW
        self.atr_p    = MA_ATR_P
        self.atr_mult = MA_ATR_M
        self.risk_pct = MA_RISK
        self._entry_bar: dict[str, int] = {}  # symbol → bar index at entry
        self._bar_cnt:   dict[str, int] = {}  # symbol → running bar count
        self.log.info(
            f"MA Crossover SL: fast={self.fast}, slow={self.slow}, "
            f"atr={self.atr_p}×{self.atr_mult}, risk={self.risk_pct:.1%} | "
            f"rsi_cap={MA_RSI_CAP}, max_hold={MA_MAX_DAYS}d"
        )

    def generate_signals(self, all_bars: dict) -> list[dict]:
        signals = []

        # ── SPY market-regime filter ──────────────────────────────────────────
        spy_above_ema = True  # default: allow if SPY not in universe
        if "SPY" in all_bars and all_bars["SPY"] is not None:
            spy_close     = all_bars["SPY"]["close"]
            spy_ema20     = sma(spy_close, 20)
            spy_above_ema = float(spy_close.iloc[-1]) > float(spy_ema20.iloc[-1])

        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < self.slow + self.atr_p + MA_RSI_P + 5:
                continue

            close = bars["close"]
            high  = bars["high"]
            low   = bars["low"]

            fast_ema = ema(close, self.fast)
            slow_ema = ema(close, self.slow)
            atr_vals = atr(high, low, close, self.atr_p)
            rsi_vals = rsi(close, MA_RSI_P)

            curr_atr   = float(atr_vals.iloc[-1])
            curr_price = float(close.iloc[-1])
            curr_rsi   = float(rsi_vals.iloc[-1])
            stop_dist  = self.atr_mult * curr_atr

            buy_cross  = crossover(fast_ema, slow_ema).iloc[-1]
            sell_cross = crossunder(fast_ema, slow_ema).iloc[-1]

            size_strength = min(1.0, self.risk_pct / (stop_dist / curr_price + 1e-9))

            # ── Time-based exit tracking ──────────────────────────────────────
            self._bar_cnt[symbol] = self._bar_cnt.get(symbol, 0) + 1
            bars_held  = self._bar_cnt[symbol] - self._entry_bar.get(
                symbol, self._bar_cnt[symbol])
            force_exit = symbol in self._entry_bar and bars_held >= MA_MAX_DAYS

            if buy_cross and spy_above_ema and curr_rsi < MA_RSI_CAP:
                self._entry_bar[symbol] = self._bar_cnt[symbol]
                signals.append({
                    "symbol":     symbol,
                    "signal":     "buy",
                    "strength":   round(size_strength, 3),
                    "reason":     (f"EMA{self.fast} crossed above EMA{self.slow} | "
                                   f"RSI {curr_rsi:.1f} < {MA_RSI_CAP} | "
                                   f"SPY above 20-EMA | "
                                   f"ATR stop at {curr_price - stop_dist:.2f}"),
                    "fast_ema":   round(float(fast_ema.iloc[-1]), 2),
                    "slow_ema":   round(float(slow_ema.iloc[-1]), 2),
                    "atr":        round(curr_atr, 4),
                    "stop_price": round(curr_price - stop_dist, 2),
                    "price":      round(curr_price, 2),
                    "rsi":        round(curr_rsi, 1),
                })
                self.log.info(f"BUY: {symbol} | strength={size_strength:.2f} RSI={curr_rsi:.1f}")

            elif sell_cross or force_exit:
                reason = (f"EMA{self.fast} crossed below EMA{self.slow}" if sell_cross
                          else f"Force exit after {bars_held}d (>{MA_MAX_DAYS}d limit)")
                self._entry_bar.pop(symbol, None)
                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": 0.5,
                    "reason":   reason,
                    "fast_ema": round(float(fast_ema.iloc[-1]), 2),
                    "slow_ema": round(float(slow_ema.iloc[-1]), 2),
                    "atr":      round(curr_atr, 4),
                    "price":    round(curr_price, 2),
                })
                self.log.info(f"SELL: {symbol} | {reason}")

            elif buy_cross:
                # Cross present but blocked by filter — log why
                reason = ("SPY below 20-EMA" if not spy_above_ema
                          else f"RSI {curr_rsi:.1f} ≥ {MA_RSI_CAP} (overbought)")
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   f"Cross blocked — {reason}",
                    "price":    round(curr_price, 2),
                    "rsi":      round(curr_rsi, 1),
                })

            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   "No crossover",
                    "price":    round(curr_price, 2),
                })

        return signals