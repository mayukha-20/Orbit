"""
market_data.py — yfinance wrapper with comprehensive error handling.

All external calls are wrapped in try/except. Every function returns a dict
with at minimum a 'status' key: "ok" | "unavailable" | "halted" | "partial".
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timezone


# ── Ticker Validation ────────────────────────────────────────────────────────

def validate_ticker(symbol: str) -> dict:
    """
    Returns {valid: bool, error?: str}.
    Downloads 5-day history; if empty or throws, ticker is invalid.
    """
    try:
        ticker = yf.Ticker(symbol.upper())
        hist = ticker.history(period="5d", auto_adjust=True)
        if hist is None or hist.empty:
            return {"valid": False, "error": f"No data found for '{symbol}'. Check the ticker symbol."}
        # Also check fast_info to catch delisted/invalid early
        info = ticker.fast_info
        if not hasattr(info, "last_price") or info.last_price is None:
            # Try to see if we at least got history
            if len(hist) == 0:
                return {"valid": False, "error": f"Ticker '{symbol}' appears to be invalid or delisted."}
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "error": f"Could not validate '{symbol}': {str(e)}"}


import time

_GLOBAL_QUOTE_CACHE = {}
CACHE_TTL = 60

# ── Core Data Fetch ──────────────────────────────────────────────────────────

def fetch_stock_data(symbol: str) -> dict:
    """
    Fetches current price, volume, 20-day history, sparkline, 52w levels.
    Implements a Global Quote Cache to prevent yfinance rate-limiting.
    """
    symbol = symbol.upper()
    now = time.time()
    if symbol in _GLOBAL_QUOTE_CACHE:
        cached_data, timestamp = _GLOBAL_QUOTE_CACHE[symbol]
        if now - timestamp < CACHE_TTL:
            return cached_data

    base = {
        "status": "unavailable",
        "symbol": symbol,
        "price": None,
        "volume": None,
        "history_df": None,
        "avg_volume_20d": None,
        "sparkline": [],
        "week52_high": None,
        "week52_low": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": None,
    }

    try:
        ticker = yf.Ticker(symbol)

        # ── 20-day + extended history ──
        hist = ticker.history(period="1y", auto_adjust=True)

        if hist is None or hist.empty:
            base["reason"] = "yfinance returned no data."
            _GLOBAL_QUOTE_CACHE[symbol] = (base, now)
            return base

        # Use last 20 trading days for core calculations
        hist_20d = hist.tail(20)

        # ── Current price & volume ──
        price, volume = _get_current_price_volume(ticker, hist)
        if price is None:
            base["reason"] = "Could not determine current price."
            _GLOBAL_QUOTE_CACHE[symbol] = (base, now)
            return base

        # ── 52-week levels ──
        week52_high = float(hist["High"].max()) if "High" in hist.columns else None
        week52_low  = float(hist["Low"].min())  if "Low"  in hist.columns else None

        # ── Average volume (20d) ──
        avg_volume_20d = (
            float(hist_20d["Volume"].mean())
            if "Volume" in hist_20d.columns and not hist_20d["Volume"].isna().all()
            else None
        )

        # ── Sparkline (last 20 closes) ──
        sparkline = (
            hist_20d["Close"].dropna().tolist()
            if "Close" in hist_20d.columns
            else []
        )

        # ── Halt & Market Closed detection ──
        status = "ok"
        reason = None
        if _is_trading_halted(hist):
            status = "halted"
            reason = "Trading appears halted — consecutive identical closes detected."
        else:
            # Check if market is closed (no trades in >16 hours)
            if not hist_20d.empty:
                last_trade = hist_20d.index[-1]
                if last_trade.tzinfo is None:
                    last_trade = last_trade.tz_localize('UTC')
                else:
                    last_trade = last_trade.tz_convert('UTC')
                
                hours_since = (datetime.now(timezone.utc) - last_trade).total_seconds() / 3600
                if hours_since > 16:
                    status = "closed"

        result = {
            **base,
            "status": status,
            "price": price,
            "volume": volume,
            "history_df": hist_20d,
            "avg_volume_20d": avg_volume_20d,
            "sparkline": [round(p, 4) for p in sparkline],
            "week52_high": round(week52_high, 4) if week52_high else None,
            "week52_low":  round(week52_low,  4) if week52_low  else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }
        
        _GLOBAL_QUOTE_CACHE[symbol] = (result, now)
        return result

    except Exception as e:
        base["reason"] = f"Fetch error: {str(e)}"
        _GLOBAL_QUOTE_CACHE[symbol] = (base, now)
        return base


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_current_price_volume(ticker, hist: pd.DataFrame) -> tuple:
    """
    Attempts fast_info first (real-time), then falls back to last history bar.
    Returns (price: float | None, volume: int | None).
    """
    price, volume = None, None

    # Try fast_info (real-time / delayed quote)
    try:
        fi = ticker.fast_info
        if hasattr(fi, "last_price") and fi.last_price is not None:
            price = float(fi.last_price)
        if hasattr(fi, "last_volume") and fi.last_volume is not None:
            volume = int(fi.last_volume)
    except Exception:
        pass

    # Fallback to last history bar
    if price is None and not hist.empty:
        try:
            price = float(hist["Close"].iloc[-1])
        except Exception:
            pass
    if volume is None and not hist.empty and "Volume" in hist.columns:
        try:
            volume = int(hist["Volume"].iloc[-1])
        except Exception:
            pass

    return price, volume


def _is_trading_halted(hist: pd.DataFrame, consecutive: int = 3) -> bool:
    """
    Returns True if the last `consecutive` Close values are identical,
    which is a strong signal of a trading halt or circuit breaker.
    """
    if "Close" not in hist.columns or len(hist) < consecutive:
        return False
    tail = hist["Close"].iloc[-consecutive:]
    # Round to 4 decimal places to avoid float precision false positives
    rounded = tail.round(4).tolist()
    return len(set(rounded)) == 1
