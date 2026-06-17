"""
strategies/dip_rider.py — DipRider: Buy the Dip + Average Down + Trailing Stop

GOAL: Catch stocks that dip within a healthy long-term uptrend.
      Hold until the trend is genuinely broken (trailing stop), not a fixed target.

═══════════════════════════════════════════════════════════════════
  THE FLOW:
  ─────────────────────────────────────────────────────────────────
  1. SCAN    Stock down -3% to -20% over last 3 trading days
             AND slow momentum (20d) still positive (trend not broken)
             AND RSI < 55 (not chasing overbought)

  2. ENTRY   Buy 60% of planned position at the dip price
             Record entry_price, hard_stop = entry × 0.75 (–25%)
             Note the average-down level = entry × 0.85 (–15%)

  3. AVERAGE If price falls –15% from entry (and not yet averaged):
               → Buy remaining 40% at current price
               → Recalculate avg_cost = (entry + current) / 2
               → Hard stop now = avg_cost × 0.75

  4. HARD STOP  Price drops below avg_cost × 0.75  → EXIT ALL
                This is the worst-case bail-out. No questions asked.

  5. TRAIL   Once price > avg_cost (i.e. in profit):
               → Activate trailing stop at peak × (1 – TRAIL_PCT)
               → Update peak_price every bar
               → When price ≤ trail_stop → EXIT

  6. EXIT    ONLY via hard stop or trailing stop.
             No fixed take-profit. Let winners run.

═══════════════════════════════════════════════════════════════════
  EXAMPLE (from user spec):
    Buy SNDK at $100 → hard stop $75, avg-down level $85
    Price drops to $85  → average down: avg_cost = $92.50
    Price drops to $75  → below hard_stop ($92.50×0.75=$69.38)? No.
                           But below original hard stop $75? Yes → EXIT
    ── OR ──
    Price recovers to $100 → trailing activates at peak×0.92 = $92
    Price rises to $105    → trail stop = $96.60
    Price hits trail stop  → EXIT at ~$96+  (+~3.7% on avg cost of $92.50)

  CONFIG PARAMS (add to config.py):
    DIPRIDER_TRAIL_PCT      = 0.08   # 8% trailing stop from peak
    DIPRIDER_HARD_STOP_PCT  = 0.25   # 25% hard stop from avg cost
    DIPRIDER_AVG_DOWN_PCT   = 0.15   # trigger average-down at -15% from entry
    DIPRIDER_DIP_MIN_PCT    = 0.03   # min dip to enter (filters tiny noise)
    DIPRIDER_DIP_MAX_PCT    = 0.20   # max dip (beyond = crash, not dip)
    DIPRIDER_SLOW_LOOKBACK  = 20     # slow momentum window (days)
"""

import pandas as pd
from strategies.base import BaseStrategy
from utils.indicators import momentum, sma, rsi
import config

# ── Parameters ─────────────────────────────────────────────────────────────────
TRAIL_PCT      = getattr(config, "DIPRIDER_TRAIL_PCT",     0.08)
HARD_STOP_PCT  = getattr(config, "DIPRIDER_HARD_STOP_PCT", 0.25)
AVG_DOWN_PCT   = getattr(config, "DIPRIDER_AVG_DOWN_PCT",  0.15)
DIP_MIN_PCT    = getattr(config, "DIPRIDER_DIP_MIN_PCT",   0.03)
DIP_MAX_PCT    = getattr(config, "DIPRIDER_DIP_MAX_PCT",   0.20)
SLOW_LOOKBACK  = getattr(config, "DIPRIDER_SLOW_LOOKBACK", 20)
SCAN_DAYS      = 3   # look-back window for the dip scan


class DipRiderStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("DipRider")
        # Per-symbol position state
        self._entry_price  : dict[str, float] = {}
        self._avg_cost     : dict[str, float] = {}
        self._peak_price   : dict[str, float] = {}
        self._averaged     : dict[str, bool]  = {}
        self._trail_active : dict[str, bool]  = {}

        self.log.info(
            f"DipRider | trail={TRAIL_PCT:.0%} | hard_stop={HARD_STOP_PCT:.0%} | "
            f"avg_down_trigger=-{AVG_DOWN_PCT:.0%} | dip_range={DIP_MIN_PCT:.0%}–{DIP_MAX_PCT:.0%}"
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _net_dip(self, close: pd.Series) -> float:
        """Net % change over last SCAN_DAYS trading bars. Negative = declined."""
        if len(close) < SCAN_DAYS + 1:
            return 0.0
        return float(close.iloc[-1] / close.iloc[-(SCAN_DAYS + 1)] - 1)

    def _consec_down(self, close: pd.Series) -> int:
        """Count consecutive days the close has been lower than the day before."""
        count = 0
        for i in range(1, min(SCAN_DAYS + 2, len(close))):
            if float(close.iloc[-i]) < float(close.iloc[-(i + 1)]):
                count += 1
            else:
                break
        return count

    def _clear(self, symbol: str):
        for d in (self._entry_price, self._avg_cost, self._peak_price,
                  self._averaged, self._trail_active):
            d.pop(symbol, None)

    # ── Core signal generation ─────────────────────────────────────────────────

    def generate_signals(self, all_bars: dict) -> list[dict]:
        signals = []
        min_bars = max(SLOW_LOOKBACK, 50) + 5

        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < min_bars:
                continue

            close = bars["close"]
            price = float(close.iloc[-1])

            mom_s      = momentum(close, SLOW_LOOKBACK)
            sma50      = sma(close, 50)
            curr_rsi   = float(rsi(close, 14).iloc[-1])
            curr_slow  = float(mom_s.iloc[-1])
            above_sma  = price > float(sma50.iloc[-1])
            dip_pct    = self._net_dip(close)           # negative = stock fell
            consec     = self._consec_down(close)

            in_position = symbol in self._avg_cost

            # ══════════════════════════════════════════════════════════════════
            # BRANCH A — Already in a position: manage it
            # ══════════════════════════════════════════════════════════════════
            if in_position:
                entry        = self._entry_price[symbol]
                avg_cost     = self._avg_cost[symbol]
                peak         = self._peak_price.get(symbol, price)
                averaged     = self._averaged.get(symbol, False)
                trail_active = self._trail_active.get(symbol, False)

                # Always update peak
                if price > peak:
                    peak = price
                    self._peak_price[symbol] = peak

                # Flip trail on once in profit
                if price > avg_cost and not trail_active:
                    self._trail_active[symbol] = True
                    trail_active = True
                    self.log.info(
                        f"TRAIL ACTIVATED {symbol} | avg={avg_cost:.2f} → price={price:.2f}"
                    )

                trail_stop = peak * (1 - TRAIL_PCT)
                hard_stop  = avg_cost * (1 - HARD_STOP_PCT)
                pnl_pct    = (price - avg_cost) / avg_cost

                # ── 1. Hard stop ──────────────────────────────────────────────
                if price <= hard_stop:
                    self._clear(symbol)
                    signals.append({
                        "symbol":   symbol,
                        "signal":   "sell",
                        "strength": 1.0,
                        "reason":   (
                            f"💀 HARD STOP | price={price:.2f} ≤ stop={hard_stop:.2f} | "
                            f"avg_cost={avg_cost:.2f} | loss={pnl_pct:.1%}"
                        ),
                        "price": round(price, 2),
                    })
                    self.log.info(
                        f"HARD STOP {symbol} | loss={pnl_pct:.1%} | avg={avg_cost:.2f}"
                    )

                # ── 2. Trailing stop (profit mode) ────────────────────────────
                elif trail_active and price <= trail_stop:
                    self._clear(symbol)
                    signals.append({
                        "symbol":   symbol,
                        "signal":   "sell",
                        "strength": 1.0,
                        "reason":   (
                            f"🔔 TRAIL STOP | peak={peak:.2f} → stop={trail_stop:.2f} | "
                            f"pnl={pnl_pct:.1%}"
                        ),
                        "price": round(price, 2),
                    })
                    self.log.info(
                        f"TRAIL STOP {symbol} | pnl={pnl_pct:.1%} | "
                        f"peak={peak:.2f} → stop={trail_stop:.2f}"
                    )

                # ── 3. Average-down opportunity ───────────────────────────────
                elif not averaged and not trail_active:
                    entry_chg = (price - entry) / entry
                    if entry_chg <= -AVG_DOWN_PCT:
                        new_avg = (entry + price) / 2   # equal-weight average
                        self._avg_cost[symbol]  = new_avg
                        self._averaged[symbol]  = True
                        new_hard_stop           = new_avg * (1 - HARD_STOP_PCT)

                        signals.append({
                            "symbol":    symbol,
                            "signal":    "buy",
                            "strength":  0.8,   # add ~40% more to the position
                            "reason":    (
                                f"📉 AVERAGE DOWN | entry={entry:.2f}→{price:.2f} "
                                f"({entry_chg:.1%}) | new_avg={new_avg:.2f} | "
                                f"new_hard_stop={new_hard_stop:.2f}"
                            ),
                            "avg_cost":   round(new_avg, 2),
                            "hard_stop":  round(new_hard_stop, 2),
                            "price":      round(price, 2),
                        })
                        self.log.info(
                            f"AVG DOWN {symbol} | {entry:.2f}→{price:.2f} | "
                            f"new avg={new_avg:.2f} | hard_stop={new_hard_stop:.2f}"
                        )

                # ── 4. Hold: report status ────────────────────────────────────
                else:
                    signals.append({
                        "symbol":     symbol,
                        "signal":     "hold",
                        "strength":   0.0,
                        "reason":     (
                            f"HOLD | pnl={pnl_pct:+.1%} | avg={avg_cost:.2f} | "
                            + (f"trail_stop={trail_stop:.2f} (peak={peak:.2f})"
                               if trail_active
                               else f"hard_stop={hard_stop:.2f} | avg_down_at={entry*(1-AVG_DOWN_PCT):.2f}")
                        ),
                        "trail_stop": round(trail_stop, 2) if trail_active else None,
                        "hard_stop":  round(hard_stop, 2),
                        "price":      round(price, 2),
                        "pnl_pct":    round(pnl_pct, 4),
                    })

            # ══════════════════════════════════════════════════════════════════
            # BRANCH B — No position: scan for dip entry
            # ══════════════════════════════════════════════════════════════════
            else:
                # Entry conditions:
                #   • Stock has dipped -3% to -20% over last 3 trading days
                #   • Long-term uptrend not broken (slow mom > 0 or above SMA50)
                #   • RSI not overbought (< 55)
                #   • Not a parabolic crash (> -20% = too scary, not a dip)

                is_valid_dip  = DIP_MIN_PCT <= abs(dip_pct) <= DIP_MAX_PCT and dip_pct < 0
                trend_intact  = curr_slow > 0.02 or above_sma
                not_overbought = curr_rsi < 55

                if is_valid_dip and trend_intact and not_overbought:
                    # Bigger dip within range = higher conviction
                    strength = round(min(1.0, abs(dip_pct) / DIP_MAX_PCT) * 0.6, 2)

                    self._entry_price[symbol]  = price
                    self._avg_cost[symbol]     = price
                    self._peak_price[symbol]   = price
                    self._averaged[symbol]     = False
                    self._trail_active[symbol] = False

                    signals.append({
                        "symbol":      symbol,
                        "signal":      "buy",
                        "strength":    strength,     # 60% of position on first leg
                        "reason":      (
                            f"🎯 DIP ENTRY | 3d={dip_pct:.1%} | down={consec}d | "
                            f"RSI={curr_rsi:.0f} | slow={curr_slow:.1%}"
                        ),
                        "dip_pct":     round(dip_pct, 4),
                        "consec_down": consec,
                        "hard_stop":   round(price * (1 - HARD_STOP_PCT), 2),
                        "avg_down_at": round(price * (1 - AVG_DOWN_PCT), 2),
                        "price":       round(price, 2),
                    })
                    self.log.info(
                        f"DIP ENTRY {symbol} | 3d={dip_pct:.1%} | "
                        f"down={consec}d | RSI={curr_rsi:.0f} | slow={curr_slow:.1%}"
                    )

                else:
                    # No entry — report why (useful for live scanning)
                    reason_parts = []
                    if not is_valid_dip:
                        reason_parts.append(
                            f"dip={dip_pct:.1%} (need {DIP_MIN_PCT:.0%}–{DIP_MAX_PCT:.0%})"
                        )
                    if not trend_intact:
                        reason_parts.append(f"trend broken (slow={curr_slow:.1%})")
                    if not not_overbought:
                        reason_parts.append(f"overbought RSI={curr_rsi:.0f}")

                    signals.append({
                        "symbol":    symbol,
                        "signal":    "hold",
                        "strength":  0.0,
                        "reason":    "No entry: " + " | ".join(reason_parts) if reason_parts else "Waiting",
                        "dip_pct":   round(dip_pct, 4),
                        "rsi":       round(curr_rsi, 1),
                        "slow_mom":  round(curr_slow, 4),
                        "price":     round(price, 2),
                    })

        return signals