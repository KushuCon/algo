"""
utils/indicators.py — Pure NumPy/Pandas technical indicators.
No external TA library dependency — easy to understand and modify.
"""

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (RSI).
    Returns values 0–100.
      > 70 = overbought (consider selling)
      < 30 = oversold (consider buying)
    """
    delta  = series.diff()
    gain   = delta.clip(lower=0)
    loss   = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def macd(series: pd.Series,
         fast: int = 12, slow: int = 26, signal: int = 9
         ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD (Moving Average Convergence Divergence).
    Returns: (macd_line, signal_line, histogram)
    Buy signal:  macd crosses ABOVE signal line
    Sell signal: macd crosses BELOW signal line
    """
    ema_fast   = ema(series, fast)
    ema_slow   = ema(series, slow)
    macd_line  = ema_fast - ema_slow
    signal_line= ema(macd_line, signal)
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(series: pd.Series, period: int = 20,
                    num_std: float = 2.0
                    ) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.
    Returns: (upper_band, middle_band, lower_band)
    Price near lower band = potential buy
    Price near upper band = potential sell
    """
    middle = sma(series, period)
    std    = series.rolling(window=period).std()
    upper  = middle + num_std * std
    lower  = middle - num_std * std
    return upper, middle, lower


def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """
    Average True Range — measures volatility.
    Higher ATR = more volatile. Useful for position sizing.
    """
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low  - close.shift()).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(alpha=1/period, adjust=False).mean()


def momentum(series: pd.Series, period: int = 20) -> pd.Series:
    """
    Rate of change momentum.
    Positive = price trending up over the period.
    """
    return (series - series.shift(period)) / series.shift(period)


def vwap(high: pd.Series, low: pd.Series, close: pd.Series,
         volume: pd.Series) -> pd.Series:
    """
    Volume Weighted Average Price.
    Price above VWAP = bullish; below = bearish.
    """
    typical_price = (high + low + close) / 3
    return (typical_price * volume).cumsum() / volume.cumsum()


def vwap_session(high: pd.Series, low: pd.Series, close: pd.Series,
                 volume: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """
    VWAP that resets each calendar day (for intraday session bars).
    """
    typical_price = (high + low + close) / 3
    tpv = typical_price * volume
    if isinstance(index, pd.DatetimeIndex):
        if index.tz is not None:
            dates = index.tz_convert("America/New_York").normalize()
        else:
            dates = pd.to_datetime(index).normalize()
    else:
        dates = pd.to_datetime(index).normalize()
    return tpv.groupby(dates).cumsum() / volume.groupby(dates).cumsum()


def crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """
    Returns True on bars where fast crosses ABOVE slow.
    Use for bullish crossover signals.
    """
    prev_below = fast.shift(1) < slow.shift(1)
    now_above  = fast >= slow
    return prev_below & now_above


def crossunder(fast: pd.Series, slow: pd.Series) -> pd.Series:
    """
    Returns True on bars where fast crosses BELOW slow.
    Use for bearish crossover signals.
    """
    prev_above = fast.shift(1) > slow.shift(1)
    now_below  = fast <= slow
    return prev_above & now_below