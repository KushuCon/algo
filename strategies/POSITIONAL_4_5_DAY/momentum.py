# """
# strategies/momentum.py — Price Momentum

# HOW IT WORKS:
#   "Winners keep winning, losers keep losing."

#   Measure how much a stock has moved over the last N days.
#   - BUY  stocks with strong positive momentum (e.g. +5% over 20 days)
#     AND where price is above its 50-day SMA (confirming uptrend)
#   - SELL when momentum reverses negative
#     OR when price drops below the 50-day SMA

# BEST FOR: Strong trending markets. Bad in mean-reverting/choppy markets.

# PARAMETERS (set in config.py):
#   MOMENTUM_LOOKBACK   = 20   # days
#   MOMENTUM_THRESHOLD  = 0.05 # require 5% gain
# """

# import pandas as pd
# from strategies.base import BaseStrategy
# from utils.indicators import momentum, sma, rsi
# import config


# MOM_VOL_MULT  = getattr(config, "MOMENTUM_VOL_MULT",  1.5)   # volume spike requirement
# MOM_SCALE_PCT = getattr(config, "MOMENTUM_SCALE_PCT", 0.03)  # scale-out at +3%


# class MomentumStrategy(BaseStrategy):
#     def __init__(self):
#         super().__init__("Momentum")
#         self.lookback  = getattr(config, "MOMENTUM_LOOKBACK",  10)   # default: 10 (was 20)
#         self.threshold = getattr(config, "MOMENTUM_THRESHOLD", 0.05)
#         self._entry_price: dict[str, float] = {}  # symbol → entry price for scale-out
#         self.log.info(
#             f"Momentum: lookback={self.lookback}, threshold={self.threshold:.0%}, "
#             f"vol_mult={MOM_VOL_MULT}×, scale_out={MOM_SCALE_PCT:.0%}"
#         )

#     def generate_signals(self, all_bars: dict) -> list[dict]:
#         signals = []

#         for symbol, bars in all_bars.items():
#             if bars is None or len(bars) < max(self.lookback, 50) + 5:
#                 continue

#             close     = bars["close"]
#             volume    = bars["volume"]
#             mom       = momentum(close, self.lookback)
#             sma50     = sma(close, 50)
#             curr_mom  = float(mom.iloc[-1])
#             price     = float(close.iloc[-1])
#             above_sma = price > float(sma50.iloc[-1])

#             # Volume spike: current bar vs 20-bar rolling average
#             avg_vol   = float(volume.rolling(20).mean().iloc[-1])
#             vol_spike = float(volume.iloc[-1]) >= MOM_VOL_MULT * avg_vol

#             # Scale-out: +3% from entry → emit sell_half + move stop to breakeven
#             entry      = self._entry_price.get(symbol)
#             scale_out  = entry is not None and price >= entry * (1 + MOM_SCALE_PCT)

#             if scale_out:
#                 signals.append({
#                     "symbol":             symbol,
#                     "signal":             "sell_half",   # PM: close 50% of position
#                     "strength":           0.5,
#                     "reason":             (f"Scale-out: +{(price/entry - 1):.1%} from "
#                                            f"entry {entry:.2f} | stop → breakeven"),
#                     "price":              round(price, 2),
#                     "entry":              round(entry, 2),
#                     "move_stop_to_entry": True,
#                 })
#                 self._entry_price.pop(symbol, None)
#                 self.log.info(f"SCALE-OUT {symbol} | +{(price/entry - 1):.1%}")

#             # BUY: strong momentum + above SMA50 + volume spike
#             elif curr_mom >= self.threshold and above_sma and vol_spike:
#                 strength = min(1.0, curr_mom / (self.threshold * 3))
#                 self._entry_price[symbol] = price
#                 signals.append({
#                     "symbol":   symbol,
#                     "signal":   "buy",
#                     "strength": round(strength, 2),
#                     "reason":   (f"Momentum {curr_mom:.1%} over {self.lookback}d | "
#                                  f"SMA50 ok | vol {volume.iloc[-1]/avg_vol:.1f}× avg"),
#                     "momentum": round(curr_mom, 4),
#                     "sma50":    round(float(sma50.iloc[-1]), 2),
#                     "price":    round(price, 2),
#                 })
#                 self.log.info(f"BUY signal: {symbol} momentum={curr_mom:.1%}")

#             # SELL: momentum turned negative OR price fell below SMA50
#             elif curr_mom < 0 or not above_sma:
#                 self._entry_price.pop(symbol, None)
#                 signals.append({
#                     "symbol":   symbol,
#                     "signal":   "sell",
#                     "strength": 0.5,
#                     "reason":   (
#                         f"Momentum negative ({curr_mom:.1%})"
#                         if curr_mom < 0
#                         else f"Price ({price:.2f}) below SMA50 ({sma50.iloc[-1]:.2f})"
#                     ),
#                     "momentum": round(curr_mom, 4),
#                     "sma50":    round(float(sma50.iloc[-1]), 2),
#                     "price":    round(price, 2),
#                 })
#                 self.log.info(f"SELL signal: {symbol} momentum={curr_mom:.1%}")

#             else:
#                 signals.append({
#                     "symbol":   symbol,
#                     "signal":   "hold",
#                     "strength": 0.0,
#                     "reason":   (f"Momentum {curr_mom:.1%} below threshold "
#                                  f"{self.threshold:.1%}"
#                                  + ("" if vol_spike else " | no volume spike")),
#                     "momentum": round(curr_mom, 4),
#                     "sma50":    round(float(sma50.iloc[-1]), 2),
#                     "price":    round(price, 2),
#                 })

#         return signals



"""
strategies/momentum.py — Enhanced Price Momentum v2

WHAT'S NEW vs v1  (and why each change helps):
─────────────────────────────────────────────────────────────────────────────
1. Dual-timeframe momentum
   • fast (10d)  = entry trigger  — catches the trend early
   • slow (20d)  = direction filter — avoids buying into short-term noise
   BUY only when BOTH agree.

2. Sell hysteresis  (-2 % threshold instead of any negative)
   • Old rule: sell whenever mom < 0  → endless whipsaws on -0.9 % ticks
   • New rule: sell only when fast_mom < -2 %  OR  (below SMA50 AND slow_mom < 0)
   • Effect: holds through the normal noise in strong trends

3. Scale-out actually executes now
   • Old: emitted "sell_half" which the backtest engine silently dropped
   • New: emits "sell" (closes position) then immediately "buy" re-entry if
     momentum is still strong (≥ 1.5× threshold)
   • This lets the strategy bank the gain AND stay on the trend

4. Momentum ranking + acceleration bonus
   • Top-3 movers (by fast momentum) get a 20 % position-size bonus
   • Stocks with improving momentum (curr > prev) get a 10 % bonus
   • Combined max strength = 1.5× → up to 15–18 % of portfolio in one name

5. Responsive volume filter  (10-bar avg, 1.2× threshold vs 20-bar, 1.5×)
   • 1.5× was too restrictive and blocked many valid SNDK/AMD entries
   • 1.2× still confirms genuine interest without over-filtering

PARAMETERS to set in config.py  (see bottom of this file for the delta):
  MOMENTUM_LOOKBACK       = 20     # slow window
  MOMENTUM_LOOKBACK_FAST  = 10     # NEW – fast window
  MOMENTUM_THRESHOLD      = 0.05   # 5 % buy trigger
  MOMENTUM_VOL_MULT       = 1.2    # was 1.5
  MOMENTUM_SCALE_PCT      = 0.05   # was 0.03 — let it run before scaling
  MOMENTUM_SELL_THRESH    = 0.02   # NEW — sell only when mom < -2 %
"""

import pandas as pd
from strategies.base import BaseStrategy
from utils.indicators import momentum, sma
import config

# ── Module-level knobs (read once, respect config overrides) ──────────────────
MOM_VOL_MULT    = getattr(config, "MOMENTUM_VOL_MULT",    1.2)   # volume filter
MOM_SCALE_PCT   = getattr(config, "MOMENTUM_SCALE_PCT",   0.05)  # scale-out at +5 %
MOM_SELL_THRESH = getattr(config, "MOMENTUM_SELL_THRESH", 0.02)  # sell when < -2 %
LOOKBACK_FAST   = getattr(config, "MOMENTUM_LOOKBACK_FAST", 10)
LOOKBACK_SLOW   = getattr(config, "MOMENTUM_LOOKBACK",     20)


class MomentumStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("Momentum")
        self.lookback_fast = LOOKBACK_FAST
        self.lookback_slow = LOOKBACK_SLOW
        self.threshold     = getattr(config, "MOMENTUM_THRESHOLD", 0.05)
        self._entry_price: dict[str, float] = {}
        self.log.info(
            f"Momentum v2 | fast={self.lookback_fast}d / slow={self.lookback_slow}d | "
            f"thresh={self.threshold:.0%} | vol={MOM_VOL_MULT}× | "
            f"scale={MOM_SCALE_PCT:.0%} | sell_hysteresis=-{MOM_SELL_THRESH:.0%}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    def generate_signals(self, all_bars: dict) -> list[dict]:
        signals = []

        # ── Pass 1: rank all symbols by fast momentum ─────────────────────────
        # Used for position-size bonuses; no forward-look — only uses bars[:today]
        fast_scores: dict[str, float] = {}
        min_bars = max(self.lookback_slow, 50) + 5

        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < min_bars:
                continue
            mom_f = momentum(bars["close"], self.lookback_fast)
            fast_scores[symbol] = float(mom_f.iloc[-1])

        # Top-3 positive movers → rank bonus
        top_movers: set[str] = {
            sym
            for sym, score in sorted(fast_scores.items(), key=lambda x: -x[1])[:3]
            if score >= self.threshold
        }

        # ── Pass 2: per-symbol signal generation ──────────────────────────────
        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < min_bars:
                continue

            close   = bars["close"]
            volume  = bars["volume"]

            mom_f   = momentum(close, self.lookback_fast)
            mom_s   = momentum(close, self.lookback_slow)
            sma50   = sma(close, 50)

            curr_fast = float(mom_f.iloc[-1])
            prev_fast = float(mom_f.iloc[-2])           # previous bar for acceleration
            curr_slow = float(mom_s.iloc[-1])
            price     = float(close.iloc[-1])
            above_sma = price > float(sma50.iloc[-1])

            # 10-bar volume avg — more responsive than 20-bar
            avg_vol   = float(volume.rolling(10).mean().iloc[-1])
            vol_spike = float(volume.iloc[-1]) >= MOM_VOL_MULT * avg_vol
            accel     = curr_fast > prev_fast            # is momentum accelerating?

            entry     = self._entry_price.get(symbol)
            scale_out = entry is not None and price >= entry * (1 + MOM_SCALE_PCT)

            # ── 1. Scale-out branch ───────────────────────────────────────────
            if scale_out:
                gain_pct = (price / entry) - 1
                self._entry_price.pop(symbol, None)

                # Close the position (actually executes in backtest engine)
                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": 1.0,
                    "reason":   f"Scale-out +{gain_pct:.1%} from entry {entry:.2f}",
                    "price":    round(price, 2),
                })
                self.log.info(f"SCALE-OUT {symbol} | +{gain_pct:.1%}")

                # Re-enter if trend is still clearly intact (higher bar than initial entry)
                if curr_fast >= self.threshold * 1.5 and above_sma:
                    re_strength = min(1.5, curr_fast / (self.threshold * 2))
                    if symbol in top_movers:
                        re_strength = min(1.5, re_strength * 1.2)
                    self._entry_price[symbol] = price
                    signals.append({
                        "symbol":   symbol,
                        "signal":   "buy",
                        "strength": round(re_strength, 2),
                        "reason":   f"Re-entry after scale-out | fast={curr_fast:.1%}",
                        "momentum": round(curr_fast, 4),
                        "price":    round(price, 2),
                    })
                    self.log.info(f"RE-ENTRY {symbol} fast-mom={curr_fast:.1%}")

            # ── 2. BUY: dual confirmation + volume ───────────────────────────
            elif (curr_fast >= self.threshold   # fast mom above trigger
                  and curr_slow > 0             # slow mom positive (trend direction)
                  and above_sma                 # price above 50d MA (regime filter)
                  and vol_spike):               # volume confirms participation

                # Position sizing: base + rank bonus + acceleration bonus
                base       = min(1.5, curr_fast / (self.threshold * 2))
                rank_bonus = 1.2 if symbol in top_movers else 1.0
                acc_bonus  = 1.1 if accel               else 1.0
                strength   = round(min(1.5, base * rank_bonus * acc_bonus), 2)

                self._entry_price[symbol] = price
                signals.append({
                    "symbol":   symbol,
                    "signal":   "buy",
                    "strength": strength,
                    "reason":   (
                        f"fast={curr_fast:.1%} slow={curr_slow:.1%} | SMA50 ✓ | "
                        f"vol {volume.iloc[-1] / avg_vol:.1f}× | "
                        f"accel={'↑' if accel else '→'} | str={strength}"
                    ),
                    "momentum": round(curr_fast, 4),
                    "sma50":    round(float(sma50.iloc[-1]), 2),
                    "price":    round(price, 2),
                })
                self.log.info(
                    f"BUY signal: {symbol} fast={curr_fast:.1%} "
                    f"slow={curr_slow:.1%} str={strength}"
                )

            # ── 3. SELL: clearly negative OR broken trend (with hysteresis) ──
            elif curr_fast < -MOM_SELL_THRESH or (not above_sma and curr_slow < 0):
                self._entry_price.pop(symbol, None)
                reason = (
                    f"Fast mom {curr_fast:.1%} < -{MOM_SELL_THRESH:.0%}"
                    if curr_fast < -MOM_SELL_THRESH
                    else f"Below SMA50 + slow mom {curr_slow:.1%} < 0"
                )
                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": 0.5,
                    "reason":   reason,
                    "momentum": round(curr_fast, 4),
                    "sma50":    round(float(sma50.iloc[-1]), 2),
                    "price":    round(price, 2),
                })
                self.log.info(f"SELL signal: {symbol} fast={curr_fast:.1%}")

            # ── 4. HOLD: transitional zone (-2 % to +5 %) ────────────────────
            # Existing positions are kept; no new entry because conditions not met
            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   (
                        f"fast={curr_fast:.1%} slow={curr_slow:.1%} | "
                        f"threshold={self.threshold:.1%}"
                        + ("" if vol_spike else " | low volume")
                        + ("" if above_sma  else " | below SMA50")
                    ),
                    "momentum": round(curr_fast, 4),
                    "sma50":    round(float(sma50.iloc[-1]), 2),
                    "price":    round(price, 2),
                })

        return signals


# ─────────────────────────────────────────────────────────────────────────────
# CONFIG.PY DELTA  — apply these changes to your config.py
# ─────────────────────────────────────────────────────────────────────────────
#
# Risk Management:
#   MAX_POSITION_PCT   = 0.12    # was 0.10  (+2 % more room for top movers)
#   TAKE_PROFIT_PCT    = 0.10    # was 0.06  (let winners run further)
#   STOP_LOSS_PCT      = 0.02    # unchanged
#
# Momentum Strategy Params (new / changed):
#   MOMENTUM_LOOKBACK       = 20    # unchanged (slow window)
#   MOMENTUM_LOOKBACK_FAST  = 10    # NEW
#   MOMENTUM_THRESHOLD      = 0.05  # unchanged
#   MOMENTUM_VOL_MULT       = 1.2   # was 1.5  (less restrictive volume gate)
#   MOMENTUM_SCALE_PCT      = 0.05  # was 0.03 (scale out after +5 %, not +3 %)
#   MOMENTUM_SELL_THRESH    = 0.02  # NEW  (sell only if mom < -2 %)
#
# ─────────────────────────────────────────────────────────────────────────────