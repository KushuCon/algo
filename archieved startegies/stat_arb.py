"""
strategies/stat_arb.py — Statistical Arbitrage via Cointegration + Z-score

How it works:
  1. Test every pair in the universe for cointegration (Engle-Granger test).
  2. For cointegrated pairs, compute the spread as: spread = A - hedge_ratio * B
  3. Normalise the spread into a rolling Z-score.
  4. Trade mean-reversion: enter when |Z| > entry_z, exit when |Z| < exit_z.

Key difference from simple PairsTrading:
  - Uses proper cointegration test (not just correlation).
  - Searches ALL symbol pairs, not just the first two.
  - Hedge ratio is estimated via OLS regression, updated every cycle.
"""

import itertools

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

from strategies.base import BaseStrategy
import config

STAT_LOOKBACK  = getattr(config, "STAT_ARB_LOOKBACK",  120)   # bars for coint test
STAT_Z_WINDOW  = getattr(config, "STAT_ARB_Z_WINDOW",   30)   # rolling mean/std window
STAT_ENTRY_Z   = getattr(config, "STAT_ARB_ENTRY_Z",    2.0)
STAT_EXIT_Z    = getattr(config, "STAT_ARB_EXIT_Z",     0.5)
STAT_PVALUE    = getattr(config, "STAT_ARB_PVALUE",     0.05)  # max p-value for coint


class StatArbStrategy(BaseStrategy):
    """
    Statistical Arbitrage — cointegration-filtered pairs, Z-score signals.

    Works best with 4+ symbols so there are enough candidate pairs.
    Recommended symbols: correlated sector peers, e.g.
      AAPL & MSFT, JPM & BAC, XOM & CVX
    """

    def __init__(self):
        super().__init__("Stat Arb (Cointegration)")
        self.lookback  = STAT_LOOKBACK
        self.z_window  = STAT_Z_WINDOW
        self.entry_z   = STAT_ENTRY_Z
        self.exit_z    = STAT_EXIT_Z
        self.pvalue    = STAT_PVALUE
        # active pair positions: {(sym_a, sym_b): "long_a" | "long_b" | None}
        self._positions: dict[tuple, str | None] = {}
        self.log.info(
            f"StatArb: lookback={self.lookback}, z_window={self.z_window}, "
            f"entry_z={self.entry_z}, exit_z={self.exit_z}, p≤{self.pvalue}"
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _ols_hedge_ratio(self, series_a: np.ndarray,
                         series_b: np.ndarray) -> float:
        """OLS regression: A = alpha + beta*B. Returns beta (hedge ratio)."""
        b = np.polyfit(series_b, series_a, 1)
        return float(b[0])

    def _z_score(self, spread: pd.Series) -> float:
        """Rolling Z-score on the last z_window bars."""
        recent = spread.iloc[-self.z_window:]
        mu  = recent.mean()
        sig = recent.std()
        if sig < 1e-9:
            return 0.0
        return float((spread.iloc[-1] - mu) / sig)

    def _cointegrated_pairs(self, all_bars: dict) -> list[tuple]:
        """Return list of (sym_a, sym_b) pairs that pass the coint test."""
        syms = [s for s, b in all_bars.items()
                if b is not None and len(b) >= self.lookback + self.z_window]
        pairs = []
        for sym_a, sym_b in itertools.combinations(syms, 2):
            a = np.log(all_bars[sym_a]["close"].iloc[-self.lookback:].values)
            b = np.log(all_bars[sym_b]["close"].iloc[-self.lookback:].values)
            try:
                _, pval, _ = coint(a, b)
            except Exception:
                continue
            if pval <= self.pvalue:
                pairs.append((sym_a, sym_b))
                self.log.debug(
                    f"Cointegrated: {sym_a}/{sym_b} p={pval:.4f}"
                )
        return pairs

    # ── main signal generation ────────────────────────────────────────────────

    def generate_signals(self, all_bars: dict) -> list[dict]:
        # Find cointegrated pairs
        coint_pairs = self._cointegrated_pairs(all_bars)

        if not coint_pairs:
            self.log.info("No cointegrated pairs found this cycle.")
            # Emit holds for all symbols
            return [
                {"symbol": s, "signal": "hold", "strength": 0.0,
                 "reason": "No cointegrated pair found", "price": float(b["close"].iloc[-1])}
                for s, b in all_bars.items() if b is not None
            ]

        signals_map: dict[str, dict] = {}  # symbol → latest signal (last wins)

        for sym_a, sym_b in coint_pairs:
            bars_a = all_bars[sym_a]
            bars_b = all_bars[sym_b]

            # Align
            common = bars_a.index.intersection(bars_b.index)
            if len(common) < self.lookback + self.z_window:
                continue

            log_a = np.log(bars_a.loc[common, "close"])
            log_b = np.log(bars_b.loc[common, "close"])

            # Estimate hedge ratio on full window
            hedge = self._ols_hedge_ratio(
                log_a.iloc[-self.lookback:].values,
                log_b.iloc[-self.lookback:].values
            )

            spread  = log_a - hedge * log_b
            curr_z  = self._z_score(spread)
            price_a = float(bars_a["close"].iloc[-1])
            price_b = float(bars_b["close"].iloc[-1])

            pair_key = (sym_a, sym_b)
            pos      = self._positions.get(pair_key)

            def _sig(sym, action, reason, strength=0.5):
                return {
                    "symbol":   sym,
                    "signal":   action,
                    "strength": strength,
                    "reason":   reason,
                    "z_score":  round(curr_z, 3),
                    "hedge":    round(hedge, 4),
                    "price":    price_a if sym == sym_a else price_b,
                }

            if curr_z > self.entry_z and pos != "long_b":
                # Spread high → A expensive vs B → short A, long B
                signals_map[sym_a] = _sig(sym_a, "sell",
                    f"StatArb: Z={curr_z:.2f}>{self.entry_z} → short {sym_a}", 0.6)
                signals_map[sym_b] = _sig(sym_b, "buy",
                    f"StatArb: Z={curr_z:.2f}>{self.entry_z} → long {sym_b}", 0.6)
                self._positions[pair_key] = "long_b"
                self.log.info(
                    f"ENTRY: short {sym_a}, long {sym_b} | Z={curr_z:.2f} "
                    f"hedge={hedge:.3f}"
                )

            elif curr_z < -self.entry_z and pos != "long_a":
                # Spread low → A cheap vs B → long A, short B
                signals_map[sym_a] = _sig(sym_a, "buy",
                    f"StatArb: Z={curr_z:.2f}<-{self.entry_z} → long {sym_a}", 0.6)
                signals_map[sym_b] = _sig(sym_b, "sell",
                    f"StatArb: Z={curr_z:.2f}<-{self.entry_z} → short {sym_b}", 0.6)
                self._positions[pair_key] = "long_a"
                self.log.info(
                    f"ENTRY: long {sym_a}, short {sym_b} | Z={curr_z:.2f} "
                    f"hedge={hedge:.3f}"
                )

            elif abs(curr_z) < self.exit_z and pos is not None:
                # Spread converged → exit both legs
                signals_map[sym_a] = _sig(sym_a, "sell",
                    f"StatArb EXIT: Z={curr_z:.2f} converged", 0.5)
                signals_map[sym_b] = _sig(sym_b, "sell",
                    f"StatArb EXIT: Z={curr_z:.2f} converged", 0.5)
                self._positions[pair_key] = None
                self.log.info(f"EXIT pair ({sym_a},{sym_b}) | Z={curr_z:.2f}")

            else:
                for sym, price in ((sym_a, price_a), (sym_b, price_b)):
                    if sym not in signals_map:
                        signals_map[sym] = _sig(sym, "hold",
                            f"StatArb: Z={curr_z:.2f}, waiting")

        # Fill holds for untouched symbols
        for sym, bars in all_bars.items():
            if bars is not None and sym not in signals_map:
                signals_map[sym] = {
                    "symbol": sym, "signal": "hold", "strength": 0.0,
                    "reason": "Not in any cointegrated pair",
                    "price":  float(bars["close"].iloc[-1]),
                }

        return list(signals_map.values())