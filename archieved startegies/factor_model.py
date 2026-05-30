
import numpy as np
import pandas as pd
from strategies.base import BaseStrategy
import config

F_MOM_LB   = getattr(config, "FACTOR_MOM_LOOKBACK", 252)
F_MOM_SKIP = getattr(config, "FACTOR_MOM_SKIP",      21)
F_MOM_W    = getattr(config, "FACTOR_MOM_WEIGHT",    0.6)
F_VAL_W    = getattr(config, "FACTOR_VAL_WEIGHT",    0.4)
F_LONG_N   = getattr(config, "FACTOR_LONG_TOP_N",    2)
F_SHORT_N  = getattr(config, "FACTOR_SHORT_BOT_N",   1)


class FactorModelStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("Factor Model (Mom + Value)")
        self.log.info(
            f"Factor: mom_lb={F_MOM_LB}, skip={F_MOM_SKIP}, "
            f"mom_w={F_MOM_W}, val_w={F_VAL_W}, "
            f"long_n={F_LONG_N}, short_n={F_SHORT_N}"
        )

    def generate_signals(self, all_bars: dict) -> list[dict]:
        required = F_MOM_LB + 10
        valid    = {s: b for s, b in all_bars.items()
                    if b is not None and len(b) >= required}
        if len(valid) < 2:
            self.log.warning(f"Need ≥2 symbols with {required} bars.")
            return []

        rows = []
        for sym, bars in valid.items():
            close = bars["close"]
            curr  = float(close.iloc[-1])

            # -- Momentum (skip-1 month) --
            skip_idx  = -(F_MOM_SKIP + 1)
            start_idx = -(F_MOM_LB + 1)
            try:
                past_price = float(close.iloc[start_idx])
                skip_price = float(close.iloc[skip_idx])
                mom        = (skip_price - past_price) / past_price
            except IndexError:
                mom = 0.0

            # -- Value: distance below 52-wk high --
            high_52 = float(close.tail(min(252, len(close))).max())
            val     = 1.0 - (curr / high_52) if high_52 > 0 else 0.0

            rows.append({"symbol": sym, "price": curr,
                         "mom": mom, "val": val})

        df = pd.DataFrame(rows)

        # Cross-sectional rank (percentile 0–1)
        df["mom_rank"] = df["mom"].rank(pct=True)
        df["val_rank"] = df["val"].rank(pct=True)
        df["score"]    = F_MOM_W * df["mom_rank"] + F_VAL_W * df["val_rank"]
        df = df.sort_values("score", ascending=False).reset_index(drop=True)

        self.log.info("Factor scores:\n" +
                      df[["symbol","mom","val","score"]].to_string(index=False))

        signals = []
        long_set  = set(df.head(F_LONG_N)["symbol"])
        short_set = set(df.tail(F_SHORT_N)["symbol"])

        for _, row in df.iterrows():
            sym = row["symbol"]
            price = row["price"]
            if sym in long_set:
                signals.append({
                    "symbol":   sym,
                    "signal":   "buy",
                    "strength": round(float(row["score"]), 3),
                    "reason":   (f"Top factor rank {df[df.symbol==sym].index[0]+1}/{len(df)} | "
                                 f"mom={row['mom']:.1%} val={row['val']:.1%}"),
                    "factor_score": round(float(row["score"]), 4),
                    "price":    round(price, 2),
                })
                self.log.info(f"BUY {sym} | score={row['score']:.3f}")
            elif sym in short_set:
                signals.append({
                    "symbol":   sym,
                    "signal":   "sell",
                    "strength": 0.5,
                    "reason":   (f"Bottom factor rank | "
                                 f"mom={row['mom']:.1%} val={row['val']:.1%}"),
                    "factor_score": round(float(row["score"]), 4),
                    "price":    round(price, 2),
                })
                self.log.info(f"SELL {sym} | score={row['score']:.3f}")
            else:
                signals.append({
                    "symbol":   sym,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   f"Mid-ranked | score={row['score']:.3f}",
                    "factor_score": round(float(row["score"]), 4),
                    "price":    round(price, 2),
                })

        return signals