"""
strategies/random_forest_strat.py — Random Forest price-direction classifier

How it works:
  1. Build a feature matrix from technical indicators (RSI, MACD, BB, ATR,
     momentum, volume ratios) on a rolling training window.
  2. Label each bar: +1 if close[t+1] > close[t] (up), else 0 (down).
  3. Train a sklearn RandomForestClassifier on the last RF_TRAIN_BARS bars.
  4. Predict the direction of the *next* bar with the latest feature vector.
  5. BUY if predicted probability of "up" > RF_BUY_THRESH,
     SELL if probability < RF_SELL_THRESH, else HOLD.

Notes:
  - Model is retrained every RF_RETRAIN_EVERY cycles (default: daily).
  - Feature set is intentionally minimal to avoid look-ahead bias.
  - Uses out-of-bag score (not test-set) for quick quality logging.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

from strategies.base import BaseStrategy
from utils.indicators import rsi, macd, bollinger_bands, atr, momentum, ema
import config

RF_TRAIN_BARS    = getattr(config, "RF_TRAIN_BARS",    200)
RF_N_ESTIMATORS  = getattr(config, "RF_N_ESTIMATORS",  100)
RF_MAX_DEPTH     = getattr(config, "RF_MAX_DEPTH",      5)
RF_BUY_THRESH    = getattr(config, "RF_BUY_THRESH",     0.65)
RF_SELL_THRESH   = getattr(config, "RF_SELL_THRESH",    0.35)
RF_RETRAIN_EVERY = getattr(config, "RF_RETRAIN_EVERY",  3)   # retrain every 3 cycles


def _build_features(bars: pd.DataFrame,
                    sector_close: pd.Series | None = None) -> pd.DataFrame:
    """
    Construct feature matrix from OHLCV bars.
    Each row = one trading day. All features are lag-safe (no future data).
    sector_close: optional aligned close series (e.g. SPY) for sector momentum feature.
    """
    close  = bars["close"]
    high   = bars["high"]
    low    = bars["low"]
    volume = bars["volume"] if "volume" in bars.columns else pd.Series(
        np.ones(len(close)), index=close.index)

    rsi14      = rsi(close, 14)
    macd_l, sig_l, hist = macd(close, 12, 26, 9)
    upper, mid, lower   = bollinger_bands(close, 20, 2.0)
    atr14      = atr(high, low, close, 14)
    mom10      = momentum(close, 10)
    mom20      = momentum(close, 20)
    ema9       = ema(close, 9)
    ema21      = ema(close, 21)

    bb_pct    = (close - lower) / (upper - lower + 1e-9)
    vol_ratio = volume / volume.rolling(20).mean()

    # ── VWAP distance (10-day rolling) ────────────────────────────────────────
    typical   = (high + low + close) / 3
    roll_vwap = ((typical * volume).rolling(10).sum()
                 / (volume.rolling(10).sum() + 1e-9))
    vwap_dist = (close - roll_vwap) / (roll_vwap + 1e-9)   # +ve = above VWAP

    # ── Sector / market momentum ──────────────────────────────────────────────
    # Pass SPY (or sector ETF) bars in generate_signals; falls back to zeros.
    if sector_close is not None:
        sec_aligned = sector_close.reindex(close.index, method="ffill")
        sector_mom5 = sec_aligned.pct_change(5)
    else:
        sector_mom5 = pd.Series(np.zeros(len(close)), index=close.index)

    feat = pd.DataFrame({
        "rsi14":       rsi14,
        "macd_hist":   hist,
        "bb_pct":      bb_pct,
        "atr_norm":    atr14 / close,
        "mom10":       mom10,
        "mom20":       mom20,
        "ema_ratio":   ema9 / ema21 - 1,
        "vol_ratio":   vol_ratio,
        "ret_1d":      close.pct_change(1),
        "ret_5d":      close.pct_change(5),
        "vwap_dist":   vwap_dist,    # new
        "sector_mom5": sector_mom5,  # new
    }, index=close.index)

    return feat.dropna()

class RandomForestStrategy(BaseStrategy):
    """
    Supervised ML strategy — Random Forest direction classifier.
    One model is trained per symbol and cached between cycles.
    """

    def __init__(self):
        super().__init__("Random Forest ML")
        self.train_bars    = RF_TRAIN_BARS
        self.n_estimators  = RF_N_ESTIMATORS
        self.max_depth     = RF_MAX_DEPTH
        self.buy_thresh    = RF_BUY_THRESH
        self.sell_thresh   = RF_SELL_THRESH
        self.retrain_every = RF_RETRAIN_EVERY
        self._models:   dict[str, RandomForestClassifier] = {}
        self._scalers:  dict[str, StandardScaler]         = {}
        self._cycle_cnt: int = 0
        self.log.info(
            f"RF: train={self.train_bars} bars, n_est={self.n_estimators}, "
            f"max_depth={self.max_depth}, buy>{self.buy_thresh}, "
            f"sell<{self.sell_thresh}"
        )

    # ── training ──────────────────────────────────────────────────────────────

    def _train(self, symbol: str, bars: pd.DataFrame,
               sector_close: pd.Series | None = None) -> bool:
        """Train (or retrain) the Random Forest for `symbol`. Returns success."""
        feat = _build_features(bars, sector_close=sector_close)
        close_aligned = bars["close"].reindex(feat.index)

        # Label: 1 if next day is up, 0 otherwise — shift(-1) = next day's return
        labels = (close_aligned.shift(-1) > close_aligned).astype(int)

        # Drop the last row (label is unknown — that's what we're predicting)
        X = feat.iloc[:-1].values
        y = labels.iloc[:-1].values

        if len(X) < 50:
            self.log.warning(f"{symbol}: too few samples ({len(X)}) to train RF.")
            return False

        # Use last train_bars samples
        X = X[-self.train_bars:]
        y = y[-self.train_bars:]

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        clf = RandomForestClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            oob_score=True,
            n_jobs=-1,
            random_state=42,
        )
        clf.fit(X_scaled, y)

        self._models[symbol]  = clf
        self._scalers[symbol] = scaler

        self.log.info(
            f"RF trained: {symbol} | samples={len(y)} | "
            f"OOB accuracy={clf.oob_score_:.2%}"
        )
        return True

    # ── prediction ────────────────────────────────────────────────────────────

    def _predict_proba_up(self, symbol: str, bars: pd.DataFrame,
                          sector_close: pd.Series | None = None) -> float | None:
        """Return probability of 'up' move for the next bar, or None on failure."""
        if symbol not in self._models:
            return None

        feat = _build_features(bars, sector_close=sector_close)
        if feat.empty:
            return None

        # Use the very last row as the live feature vector
        X_live = feat.iloc[[-1]].values
        X_scaled = self._scalers[symbol].transform(X_live)
        proba = self._models[symbol].predict_proba(X_scaled)[0]

        # proba shape: [P(down), P(up)]
        classes = list(self._models[symbol].classes_)
        up_idx  = classes.index(1) if 1 in classes else -1
        return float(proba[up_idx]) if up_idx >= 0 else 0.5

    # ── main loop ─────────────────────────────────────────────────────────────

    def generate_signals(self, all_bars: dict) -> list[dict]:
        self._cycle_cnt += 1
        should_retrain = (self._cycle_cnt % self.retrain_every == 0)

        # Use SPY as sector/market proxy; None if not in universe
        spy_close = (
            all_bars["SPY"]["close"]
            if "SPY" in all_bars and all_bars["SPY"] is not None
            else None
        )

        signals = []
        for symbol, bars in all_bars.items():
            if bars is None or len(bars) < self.train_bars + 30:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   f"Insufficient bars ({0 if bars is None else len(bars)})",
                    "price":    float(bars["close"].iloc[-1]) if bars is not None else 0.0,
                })
                continue

            price = float(bars["close"].iloc[-1])

            # Train / retrain
            if should_retrain or symbol not in self._models:
                ok = self._train(symbol, bars, sector_close=spy_close)
                if not ok:
                    signals.append({
                        "symbol": symbol, "signal": "hold",
                        "strength": 0.0, "reason": "RF training failed",
                        "price": price,
                    })
                    continue

            prob_up = self._predict_proba_up(symbol, bars, sector_close=spy_close)
            if prob_up is None:
                signals.append({
                    "symbol": symbol, "signal": "hold",
                    "strength": 0.0, "reason": "RF prediction failed",
                    "price": price,
                })
                continue

            # Signal logic
            if prob_up >= self.buy_thresh:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "buy",
                    "strength": round(prob_up, 3),
                    "reason":   f"RF P(up)={prob_up:.2%} ≥ {self.buy_thresh:.0%}",
                    "prob_up":  round(prob_up, 4),
                    "price":    round(price, 2),
                })
                self.log.info(f"BUY {symbol} | RF P(up)={prob_up:.2%}")

            elif prob_up <= self.sell_thresh:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": round(1.0 - prob_up, 3),
                    "reason":   f"RF P(up)={prob_up:.2%} ≤ {self.sell_thresh:.0%}",
                    "prob_up":  round(prob_up, 4),
                    "price":    round(price, 2),
                })
                self.log.info(f"SELL {symbol} | RF P(up)={prob_up:.2%}")

            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   f"RF P(up)={prob_up:.2%} in neutral zone",
                    "prob_up":  round(prob_up, 4),
                    "price":    round(price, 2),
                })

        return signals