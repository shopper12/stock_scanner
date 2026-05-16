from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(close: pd.Series) -> float:
    if close.empty:
        return 0.0
    peak = close.cummax()
    dd = close / peak - 1
    return float(dd.min())


def annualized_volatility(close: pd.Series) -> float:
    returns = close.pct_change().dropna()
    if returns.empty:
        return 0.0
    return float(returns.std() * np.sqrt(252))


def momentum(close: pd.Series, days: int) -> float:
    if len(close) <= days:
        days = max(1, len(close) - 1)
    return float(close.iloc[-1] / close.iloc[-days] - 1)


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window).mean()


def score_clip(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return float(max(lower, min(upper, value)))
