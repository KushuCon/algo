"""
strategies/lstm_strat.py — LSTM (Long Short-Term Memory) price-direction strategy

How it works:
  1. Prepare a sliding-window sequence dataset from OHLCV + indicators.
     Each input = last LSTM_SEQ_LEN bars of features → label = next-day direction.
  2. Train a 2-layer LSTM (via PyTorch) on the last LSTM_TRAIN_BARS bars.
  3. At inference, feed the most recent sequence and get P(up).
  4. BUY / SELL / HOLD based on probability thresholds (same as RF strategy).

PyTorch is used for flexibility and speed. The model is intentionally small
(hidden=64, 2 layers) to avoid overfitting on limited financial data.

Dependencies: torch (added to requirements.txt)

Graceful degradation: if torch is not installed, the strategy logs a clear
error and emits HOLD for all symbols rather than crashing the bot.
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

from strategies.base import BaseStrategy
from utils.indicators import rsi, macd, bollinger_bands, atr, momentum, ema, adx
import config

LSTM_SEQ_LEN     = getattr(config, "LSTM_SEQ_LEN",       10)    # input window — reduced from 20    # input window (bars)
LSTM_TRAIN_BARS  = getattr(config, "LSTM_TRAIN_BARS",    300)    # training set size
LSTM_HIDDEN      = getattr(config, "LSTM_HIDDEN",         64)
LSTM_LAYERS      = getattr(config, "LSTM_LAYERS",          2)
LSTM_EPOCHS      = getattr(config, "LSTM_EPOCHS",         20)
LSTM_LR          = getattr(config, "LSTM_LR",           1e-3)
LSTM_BATCH       = getattr(config, "LSTM_BATCH",          32)
LSTM_BUY_THRESH  = getattr(config, "LSTM_BUY_THRESH",    0.60)
LSTM_SELL_THRESH = getattr(config, "LSTM_SELL_THRESH",   0.40)
LSTM_RETRAIN_EVERY = getattr(config, "LSTM_RETRAIN_EVERY", 5)    # cycles

# ── optional torch import ─────────────────────────────────────────────────────
try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    _TORCH_OK = True
except ImportError:
    _TORCH_OK = False


# ── Model definition ──────────────────────────────────────────────────────────

if _TORCH_OK:
    class _LSTMNet(nn.Module):
        """Minimal 2-layer LSTM classifier → binary output (up/down)."""

        def __init__(self, n_features: int, hidden: int, n_layers: int,
                     dropout: float = 0.2):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size=n_features,
                hidden_size=hidden,
                num_layers=n_layers,
                batch_first=True,
                dropout=dropout if n_layers > 1 else 0.0,
            )
            self.fc   = nn.Linear(hidden, 1)
            self.sig  = nn.Sigmoid()

        def forward(self, x):                   # x: (batch, seq_len, features)
            out, _ = self.lstm(x)
            out     = self.fc(out[:, -1, :])    # take last time-step
            return self.sig(out).squeeze(-1)    # (batch,)


# ── Feature builder (same as RF for consistency) ──────────────────────────────

def _build_features(bars: pd.DataFrame) -> pd.DataFrame:
    close  = bars["close"]
    high   = bars["high"]
    low    = bars["low"]
    volume = bars.get("volume", pd.Series(np.ones(len(close)), index=close.index))

    rsi14             = rsi(close, 14)
    _, _, macd_hist   = macd(close, 12, 26, 9)
    upper, _, lower   = bollinger_bands(close, 20, 2.0)
    atr14             = atr(high, low, close, 14)
    mom10             = momentum(close, 10)
    mom20             = momentum(close, 20)
    ema9              = ema(close, 9)
    ema21             = ema(close, 21)

    adx14  = adx(high, low, close, 14)
    regime = (adx14 > 25).astype(float)   # 1.0 = trending, 0.0 = ranging

    feat = pd.DataFrame({
        "rsi14":     rsi14,
        "macd_hist": macd_hist,
        "bb_pct":    (close - lower) / (upper - lower + 1e-9),
        "atr_norm":  atr14 / close,
        "mom10":     mom10,
        "mom20":     mom20,
        "ema_ratio": ema9 / ema21 - 1,
        "vol_ratio": volume / volume.rolling(20).mean(),
        "ret_1d":    close.pct_change(1),
        "ret_5d":    close.pct_change(5),
        "regime":    regime,   # new: market regime indicator
    }, index=close.index)

    return feat.dropna()


# ── Strategy class ────────────────────────────────────────────────────────────

class LSTMStrategy(BaseStrategy):
    """
    LSTM sequence-to-signal strategy.
    Trains a small PyTorch LSTM per symbol; retrains every N cycles.
    Falls back gracefully if PyTorch is unavailable.
    """

    def __init__(self):
        super().__init__("LSTM ML")
        self.seq_len      = LSTM_SEQ_LEN
        self.train_bars   = LSTM_TRAIN_BARS
        self.hidden       = LSTM_HIDDEN
        self.n_layers     = LSTM_LAYERS
        self.epochs       = LSTM_EPOCHS
        self.lr           = LSTM_LR
        self.batch        = LSTM_BATCH
        self.buy_thresh   = LSTM_BUY_THRESH
        self.sell_thresh  = LSTM_SELL_THRESH
        self.retrain_every = LSTM_RETRAIN_EVERY
        self._models: dict[str, "_LSTMNet"] = {}
        self._scalers_mean: dict[str, np.ndarray] = {}
        self._scalers_std:  dict[str, np.ndarray] = {}
        # RF ensemble
        self._rf_models:  dict[str, RandomForestClassifier] = {}
        self._rf_scalers: dict[str, StandardScaler]         = {}
        self._cycle_cnt = 0

        if not _TORCH_OK:
            self.log.error(
                "PyTorch not installed! Run: pip install torch  "
                "The LSTM strategy will emit HOLD until torch is available."
            )
        else:
            self.log.info(
                f"LSTM: seq={self.seq_len}, train={self.train_bars}, "
                f"hidden={self.hidden}, layers={self.n_layers}, "
                f"epochs={self.epochs}, retrain_every={self.retrain_every}"
            )

    # ── RF ensemble helpers ───────────────────────────────────────────────────

    def _train_rf(self, symbol: str,
                  feat_2d: np.ndarray, labels: np.ndarray) -> None:
        """Train a lightweight RF on the same feature set for ensemble gating."""
        if len(feat_2d) < 50:
            return
        scaler = StandardScaler()
        X = scaler.fit_transform(feat_2d[-self.train_bars:])
        y = labels[-self.train_bars:]
        clf = RandomForestClassifier(n_estimators=50, max_depth=4,
                                     n_jobs=-1, random_state=42)
        clf.fit(X, y)
        self._rf_models[symbol]  = clf
        self._rf_scalers[symbol] = scaler

    def _rf_predict(self, symbol: str, feat_row: np.ndarray) -> float:
        """RF P(up). Returns 0.5 (neutral) when model is absent."""
        if symbol not in self._rf_models:
            return 0.5
        X = self._rf_scalers[symbol].transform(feat_row[np.newaxis])
        proba   = self._rf_models[symbol].predict_proba(X)[0]
        classes = list(self._rf_models[symbol].classes_)
        up_idx  = classes.index(1) if 1 in classes else -1
        return float(proba[up_idx]) if up_idx >= 0 else 0.5

    
    # ── normalisation ─────────────────────────────────────────────────────────

    def _normalise(self, X: np.ndarray, symbol: str,
                   fit: bool = False) -> np.ndarray:
        if fit:
            self._scalers_mean[symbol] = X.mean(axis=0)
            self._scalers_std[symbol]  = X.std(axis=0) + 1e-9
        mean = self._scalers_mean[symbol]
        std  = self._scalers_std[symbol]
        return (X - mean) / std

    # ── dataset builder ───────────────────────────────────────────────────────

    def _make_sequences(self, feat: np.ndarray,
                        labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Sliding-window sequences: X shape=(n, seq_len, features), y shape=(n,)."""
        X, y = [], []
        for i in range(self.seq_len, len(feat)):
            X.append(feat[i - self.seq_len: i])
            y.append(labels[i])
        return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)

    # ── training ──────────────────────────────────────────────────────────────

    def _train(self, symbol: str, bars: pd.DataFrame) -> bool:
        if not _TORCH_OK:
            return False

        feat_df = _build_features(bars)
        close   = bars["close"].reindex(feat_df.index)
        labels  = (close.shift(-1) > close).astype(float).values

        raw    = feat_df.values[:-1]          # drop last (unknown label)
        labels = labels[:-1]

        if len(raw) < self.seq_len + 30:
            self.log.warning(f"{symbol}: too few rows ({len(raw)}) for LSTM.")
            return False

        # Keep last train_bars
        raw    = raw[-self.train_bars:]
        labels = labels[-self.train_bars:]

        X_norm = self._normalise(raw, symbol, fit=True)
        X_seq, y_seq = self._make_sequences(X_norm, labels)

        if len(X_seq) < 10:
            return False

        device = torch.device("cpu")
        X_t = torch.tensor(X_seq)
        y_t = torch.tensor(y_seq)

        dataset = TensorDataset(X_t, y_t)
        loader  = DataLoader(dataset, batch_size=self.batch, shuffle=True)

        n_features = X_seq.shape[2]
        model = _LSTMNet(n_features, self.hidden, self.n_layers).to(device)
        opt   = torch.optim.Adam(model.parameters(), lr=self.lr)
        loss_fn = nn.BCELoss()

        model.train()
        final_loss = 0.0
        for epoch in range(self.epochs):
            epoch_loss = 0.0
            for xb, yb in loader:
                opt.zero_grad()
                pred = model(xb)
                loss = loss_fn(pred, yb)
                loss.backward()
                opt.step()
                epoch_loss += loss.item()
            final_loss = epoch_loss / len(loader)

        self._models[symbol] = model

        # Train RF ensemble on the same flat (unsequenced) features
        self._train_rf(symbol, raw, labels)

        self.log.info(
            f"LSTM trained: {symbol} | seqs={len(X_seq)} | "
            f"final_loss={final_loss:.4f} | RF ensemble updated"
        )
        return True

    # ── inference ─────────────────────────────────────────────────────────────

    def _predict_proba_up(self, symbol: str,
                          bars: pd.DataFrame) -> float | None:
        if not _TORCH_OK or symbol not in self._models:
            return None

        feat_df = _build_features(bars)
        if len(feat_df) < self.seq_len:
            return None

        raw    = feat_df.values[-self.seq_len:]
        X_norm = self._normalise(raw, symbol, fit=False)
        X_t    = torch.tensor(X_norm[np.newaxis], dtype=torch.float32)  # (1, seq, feat)

        self._models[symbol].eval()
        with torch.no_grad():
            prob = float(self._models[symbol](X_t).item())
        return prob

    # ── main ──────────────────────────────────────────────────────────────────

    def generate_signals(self, all_bars: dict) -> list[dict]:
        self._cycle_cnt += 1
        should_retrain = (self._cycle_cnt % self.retrain_every == 0)

        signals = []
        for symbol, bars in all_bars.items():
            price = float(bars["close"].iloc[-1]) if bars is not None else 0.0

            if not _TORCH_OK:
                signals.append({
                    "symbol": symbol, "signal": "hold",
                    "strength": 0.0,
                    "reason": "PyTorch not installed — run: pip install torch",
                    "price": price,
                })
                continue

            if bars is None or len(bars) < self.train_bars + self.seq_len + 30:
                signals.append({
                    "symbol": symbol, "signal": "hold",
                    "strength": 0.0,
                    "reason": f"Insufficient bars ({0 if bars is None else len(bars)})",
                    "price": price,
                })
                continue

            if should_retrain or symbol not in self._models:
                ok = self._train(symbol, bars)
                if not ok:
                    signals.append({
                        "symbol": symbol, "signal": "hold",
                        "strength": 0.0, "reason": "LSTM training failed",
                        "price": price,
                    })
                    continue

            prob_up = self._predict_proba_up(symbol, bars)
            if prob_up is None:
                signals.append({
                    "symbol": symbol, "signal": "hold",
                    "strength": 0.0, "reason": "LSTM inference failed",
                    "price": price,
                })
                continue

            # ── RF ensemble agreement gate ─────────────────────────────────────
            feat_df  = _build_features(bars)
            rf_prob  = (self._rf_predict(symbol, feat_df.values[-1])
                        if not feat_df.empty else 0.5)

            lstm_buy  = prob_up >= self.buy_thresh
            lstm_sell = prob_up <= self.sell_thresh
            rf_buy    = rf_prob  >= self.buy_thresh
            rf_sell   = rf_prob  <= self.sell_thresh

            if lstm_buy and rf_buy:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "buy",
                    "strength": round((prob_up + rf_prob) / 2, 3),
                    "reason":   f"LSTM={prob_up:.2%} + RF={rf_prob:.2%} both agree ↑",
                    "prob_up":  round(prob_up, 4),
                    "rf_prob":  round(rf_prob, 4),
                    "price":    round(price, 2),
                })
                self.log.info(f"BUY {symbol} | LSTM={prob_up:.2%} RF={rf_prob:.2%}")

            elif lstm_sell and rf_sell:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "sell",
                    "strength": round((2.0 - prob_up - rf_prob) / 2, 3),
                    "reason":   f"LSTM={prob_up:.2%} + RF={rf_prob:.2%} both agree ↓",
                    "prob_up":  round(prob_up, 4),
                    "rf_prob":  round(rf_prob, 4),
                    "price":    round(price, 2),
                })
                self.log.info(f"SELL {symbol} | LSTM={prob_up:.2%} RF={rf_prob:.2%}")

            else:
                signals.append({
                    "symbol":   symbol,
                    "signal":   "hold",
                    "strength": 0.0,
                    "reason":   f"No ensemble agreement | LSTM={prob_up:.2%} RF={rf_prob:.2%}",
                    "prob_up":  round(prob_up, 4),
                    "rf_prob":  round(rf_prob, 4),
                    "price":    round(price, 2),
                })

        return signals