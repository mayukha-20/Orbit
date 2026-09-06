"""
change_engine.py — Change score computation, 52-week level checks,
                    and human-readable reason string generation.
"""

import pandas as pd


# ── Change Score ─────────────────────────────────────────────────────────────

def compute_change_score(
    current_price: float,
    last_price: float,
    ewma_vol: float,
    current_volume: int | None,
    avg_volume_20d: float | None,
) -> dict:
    """
    Returns:
        {
          score: float,
          price_move_pct: float,        # raw abs % move
          volatility_ratio: float,      # move / ewma_vol (how many sigma)
          volume_ratio: float | None,
          is_meaningful: bool,
          direction: "up" | "down" | "flat"
        }
    """
    # Direction
    raw_move = current_price - last_price
    if abs(raw_move) < 1e-6:
        direction = "flat"
    elif raw_move > 0:
        direction = "up"
    else:
        direction = "down"

    price_move_pct = abs(raw_move / last_price) if last_price != 0 else 0.0
    volatility_ratio = price_move_pct / ewma_vol if ewma_vol > 0 else 0.0

    volume_ratio = None
    if current_volume and avg_volume_20d and avg_volume_20d > 0:
        volume_ratio = current_volume / avg_volume_20d

    # Weighted score
    vol_component = 0.7 * volatility_ratio
    vol_ratio_component = 0.3 * (volume_ratio if volume_ratio is not None else 1.0)
    score = vol_component + vol_ratio_component

    # Meaningful flag
    vol_flag = volatility_ratio >= 1.5
    vol_ratio_flag = (volume_ratio is not None) and (volume_ratio >= 1.5)
    is_meaningful = vol_flag or vol_ratio_flag

    return {
        "score": round(score, 4),
        "price_move_pct": round(price_move_pct * 100, 3),  # as percentage
        "volatility_ratio": round(volatility_ratio, 3),
        "volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
        "is_meaningful": is_meaningful,
        "direction": direction,
    }


# ── 52-Week Level Check ──────────────────────────────────────────────────────

def check_52w_levels(
    current_price: float,
    last_price: float,
    week52_high: float | None,
    week52_low: float | None,
) -> dict:
    """
    Checks whether the price crossed a 52-week high or low since last visit.
    'Crossed' means last_price was below/above the level and current_price is at/beyond it.
    """
    crossed_high = False
    crossed_low  = False

    if week52_high is not None and last_price < week52_high <= current_price:
        crossed_high = True
    if week52_low is not None and last_price > week52_low >= current_price:
        crossed_low = True

    # Percent of 52w range (for the visual gauge: 0.0 = at 52w low, 1.0 = at 52w high)
    pct_of_range = None
    if week52_high is not None and week52_low is not None:
        rng = week52_high - week52_low
        if rng > 0:
            pct_of_range = round((current_price - week52_low) / rng, 4)
            pct_of_range = max(0.0, min(1.0, pct_of_range))

    return {
        "crossed_52w_high": crossed_high,
        "crossed_52w_low": crossed_low,
        "pct_of_52w_range": pct_of_range,
    }


# ── Reason String Generator ──────────────────────────────────────────────────

def generate_reason_string(
    symbol: str,
    data_status: str,
    change_result: dict | None,
    level_result: dict | None,
    used_fallback_vol: bool = False,
    last_updated: str | None = None,
) -> str:
    """
    Generates a plain-English explanation for display.

    data_status: "ok" | "unavailable" | "halted" | "partial" | "first_visit"
    """
    sym = symbol.upper()

    # ── Special states first ──
    if data_status == "first_visit":
        return (
            f"{sym} — first snapshot recorded. "
            "Return later to see what's changed."
        )

    if data_status == "halted":
        return (
            f"{sym} — trading appears halted. "
            "No fresh price movement detected; treating as notable."
        )

    if data_status in ("unavailable", "partial"):
        ts = f" (last known: {_fmt_timestamp(last_updated)})" if last_updated else ""
        return (
            f"{sym} — couldn't refresh data{ts}. "
            "Showing last cached price."
        )

    # ── Normal scored state ──
    if change_result is None:
        return f"{sym} — no comparison data available."

    move_pct   = change_result["price_move_pct"]
    vol_ratio  = change_result["volatility_ratio"]
    vol_r      = change_result["volume_ratio"]
    direction  = change_result["direction"]
    meaningful = change_result["is_meaningful"]

    dir_word = {"up": "▲ up", "down": "▼ down", "flat": "flat"}.get(direction, "moved")

    parts = []

    if move_pct < 0.01:
        parts.append(f"{sym} — essentially flat (< 0.01% move).")
    else:
        parts.append(
            f"{sym} {dir_word} {move_pct:.2f}% — "
            f"{vol_ratio:.1f}× its usual daily swing"
        )
        if vol_r is not None:
            parts.append(f", on {vol_r:.1f}× normal volume")
        parts.append(".")

    # Bonus signals
    if level_result:
        if level_result.get("crossed_52w_high"):
            parts.append(" Also crossed its 52-week high.")
        if level_result.get("crossed_52w_low"):
            parts.append(" Also crossed its 52-week low.")

    if used_fallback_vol:
        parts.append(" (New listing — using conservative volatility baseline.)")

    if not meaningful and move_pct >= 0.01:
        parts.append(" Within normal range.")

    return "".join(parts)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_timestamp(iso_str: str) -> str:
    """Formats an ISO timestamp to a readable string like '2 Sep 14:32 UTC'."""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d %b %H:%M UTC").lstrip('0')
    except Exception:
        return iso_str or "unknown"
