"""
volatility.py — EWMA volatility computation with fallback for thin history.
"""

import pandas as pd

# Conservative fallback for stocks with insufficient history (new listings, IPOs).
# 1.5% represents a mid-market average for a typical trading day.
DEFAULT_VOLATILITY = 0.015

# Minimum data points required to trust our own EWMA calculation
MIN_HISTORY_POINTS = 3


def compute_ewma_volatility(history_df: pd.DataFrame) -> tuple[float, bool]:
    """
    Computes EWMA of daily absolute % price changes over the history window.

    Formula:
        daily_pct_change[i] = abs((close[i] - close[i-1]) / close[i-1])
        ewma = EWM(span=10).mean() of daily_pct_change

    Returns:
        (ewma_volatility: float, used_fallback: bool)

    used_fallback=True means we had insufficient data and used DEFAULT_VOLATILITY.
    """
    if history_df is None or "Close" not in history_df.columns:
        return DEFAULT_VOLATILITY, True

    closes = history_df["Close"].dropna()

    if len(closes) < MIN_HISTORY_POINTS:
        return DEFAULT_VOLATILITY, True

    try:
        daily_pct = closes.pct_change().abs().dropna()

        if daily_pct.empty or daily_pct.isna().all():
            return DEFAULT_VOLATILITY, True

        ewma_series = daily_pct.ewm(span=10, min_periods=1).mean()
        result = float(ewma_series.iloc[-1])

        # Sanity check: if EWMA is zero or absurdly large, fall back
        if result <= 0 or result > 1.0:
            return DEFAULT_VOLATILITY, True

        return result, False

    except Exception:
        return DEFAULT_VOLATILITY, True


def compute_volatility_trend(history_df: pd.DataFrame) -> str:
    """
    Compares first-half vs second-half EWMA volatility to answer:
    is this stock getting MORE volatile or LESS volatile lately?

    Returns: "rising" | "falling" | "stable"
    """
    if history_df is None or "Close" not in history_df.columns:
        return "stable"
    closes = history_df["Close"].dropna()
    if len(closes) < 6:
        return "stable"
    try:
        daily_pct = closes.pct_change().abs().dropna()
        ewma_series = daily_pct.ewm(span=10, min_periods=1).mean().dropna()
        if len(ewma_series) < 4:
            return "stable"
        mid = len(ewma_series) // 2
        first_half_avg = float(ewma_series.iloc[:mid].mean())
        second_half_avg = float(ewma_series.iloc[mid:].mean())
        if first_half_avg == 0:
            return "stable"
        ratio = second_half_avg / first_half_avg
        if ratio > 1.15:
            return "rising"
        elif ratio < 0.85:
            return "falling"
        return "stable"
    except Exception:
        return "stable"


def compute_avg_volume_20d(history_df: pd.DataFrame) -> float | None:
    """Returns the mean daily volume over the history window."""
    if history_df is None or "Volume" not in history_df.columns:
        return None
    volumes = history_df["Volume"].dropna()
    if volumes.empty:
        return None
    avg = float(volumes.mean())
    return avg if avg > 0 else None


def classify_volatility(ewma_vol: float) -> str:
    """
    Returns a human-readable volatility category badge label.
    Thresholds are approximate market norms:
        LOW    < 1%   daily swing (e.g. large-cap blue chips)
        MEDIUM 1–3%   daily swing (e.g. typical mid-cap)
        HIGH   > 3%   daily swing (e.g. small-cap, crypto-adjacent)
    """
    if ewma_vol < 0.010:
        return "LOW"
    elif ewma_vol < 0.030:
        return "MEDIUM"
    else:
        return "HIGH"
