
import numpy as np
import pandas as pd
from strategies.base import BaseStrategy
import config

PAIRS_LOOKBACK = getattr(config, "PAIRS_LOOKBACK", 60)
PAIRS_ENTRY_Z  = getattr(config, "PAIRS_ENTRY_Z",  2.0)
PAIRS_EXIT_Z   = getattr(config, "PAIRS_EXIT_Z",   0.5)


class PairsTradingStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("Pairs Trading")
        self.lookback = PAIRS_LOOKBACK
        self.entry_z  = PAIRS_ENTRY_Z
        self.exit_z   = PAIRS_EXIT_Z
        self.log.info(
            f"Pairs Trading: lookback={self.lookback}, "
            f"entry_z={self.entry_z}, exit_z={self.exit_z}"
        )
        # Track which leg direction we're currently in
        self._position = None  # "long_A" | "long_B" | None

    def generate_signals(self, all_bars: dict) -> list[dict]:
        syms = [s for s, b in all_bars.items() if b is not None]
        if len(syms) < 2:
            self.log.warning("Pairs Trading needs exactly 2 symbols.")
            return []

        sym_a, sym_b = syms[0], syms[1]
        bars_a = all_bars[sym_a]
        bars_b = all_bars[sym_b]

        # Align on common dates
        common = bars_a.index.intersection(bars_b.index)
        if len(common) < self.lookback + 10:
            return []

        log_a = np.log(bars_a.loc[common, "close"])
        log_b = np.log(bars_b.loc[common, "close"])

        # Rolling OLS beta (hedge ratio)
        window = self.lookback
        betas  = []
        for i in range(len(common)):
            start = max(0, i - window + 1)
            la = log_a.iloc[start:i+1].values
            lb = log_b.iloc[start:i+1].values
            if len(la) < 10:
                betas.append(1.0)
                continue
            beta = np.polyfit(lb, la, 1)[0]
            betas.append(float(beta))

        beta_series = pd.Series(betas, index=common)
        spread      = log_a - beta_series * log_b

        # Rolling Z-score
        roll_mean = spread.rolling(window).mean()
        roll_std  = spread.rolling(window).std()
        z_score   = (spread - roll_mean) / (roll_std + 1e-9)

        curr_z   = float(z_score.iloc[-1])
        curr_beta = float(beta_series.iloc[-1])

        price_a = float(bars_a["close"].iloc[-1])
        price_b = float(bars_b["close"].iloc[-1])

        signals = []

        def _make_sig(sym, action, reason, strength=0.5):
            return {"symbol": sym, "signal": action,
                    "strength": strength, "reason": reason,
                    "z_score": round(curr_z, 3), "beta": round(curr_beta, 3),
                    "price": price_a if sym == sym_a else price_b}

        # ── Entry logic ────────────────────────────────────────────────────────
        if curr_z > self.entry_z and self._position != "long_B":
            # Spread too high → A overpriced vs B → SELL A, BUY B
            signals.append(_make_sig(sym_a, "sell",
                f"Pairs: Z={curr_z:.2f} > {self.entry_z} → short {sym_a}", 0.6))
            signals.append(_make_sig(sym_b, "buy",
                f"Pairs: Z={curr_z:.2f} > {self.entry_z} → long {sym_b}", 0.6))
            self._position = "long_B"
            self.log.info(f"PAIRS ENTRY: short {sym_a}, long {sym_b} | Z={curr_z:.2f}")

        elif curr_z < -self.entry_z and self._position != "long_A":
            # Spread too low → A underpriced vs B → BUY A, SELL B
            signals.append(_make_sig(sym_a, "buy",
                f"Pairs: Z={curr_z:.2f} < -{self.entry_z} → long {sym_a}", 0.6))
            signals.append(_make_sig(sym_b, "sell",
                f"Pairs: Z={curr_z:.2f} < -{self.entry_z} → short {sym_b}", 0.6))
            self._position = "long_A"
            self.log.info(f"PAIRS ENTRY: long {sym_a}, short {sym_b} | Z={curr_z:.2f}")

        # ── Exit logic (spread has converged) ─────────────────────────────────
        elif abs(curr_z) < self.exit_z and self._position is not None:
            signals.append(_make_sig(sym_a, "sell",
                f"Pairs EXIT: Z converged to {curr_z:.2f}", 0.5))
            signals.append(_make_sig(sym_b, "sell",
                f"Pairs EXIT: Z converged to {curr_z:.2f}", 0.5))
            self._position = None
            self.log.info(f"PAIRS EXIT: Z={curr_z:.2f} converged")

        else:
            signals.append(_make_sig(sym_a, "hold",
                f"Pairs: Z={curr_z:.2f}, waiting for |Z|>{self.entry_z}"))
            signals.append(_make_sig(sym_b, "hold",
                f"Pairs: Z={curr_z:.2f}, waiting for |Z|>{self.entry_z}"))

        return signals
