"""
app.py — Flask application: routes, orchestration, CORS headers.
Run with: python app.py
"""

import os
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, send_from_directory

import db
import market_data as md
import volatility as vol
import change_engine as ce

app = Flask(__name__, static_folder=None)
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")


# ── Startup ───────────────────────────────────────────────────────────────────

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return response


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if path and os.path.exists(os.path.join(FRONTEND_DIR, path)):
        return send_from_directory(FRONTEND_DIR, path)
    return send_from_directory(FRONTEND_DIR, "index.html")


# ── GET /search ───────────────────────────────────────────────────────────────

@app.route("/search", methods=["GET"])
def search_stocks():
    """
    Search stocks by company name or partial ticker using yfinance Search.
    Returns up to 8 results: {symbol, name, exchange, type}
    Query param: ?q=apple
    """
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([]), 200
    try:
        import yfinance as yf
        results = yf.Search(q, news_count=0, max_results=10).quotes
        ALLOWED = {"EQUITY", "ETF", "CRYPTOCURRENCY", "MUTUALFUND"}
        out, seen = [], set()
        for r in results:
            sym   = r.get("symbol", "")
            qtype = r.get("quoteType", "")
            if not sym or sym in seen or qtype not in ALLOWED:
                continue
            seen.add(sym)
            out.append({
                "symbol":   sym,
                "name":     r.get("shortname") or r.get("longname") or sym,
                "exchange": r.get("exchange", ""),
                "type":     qtype,
            })
            if len(out) >= 8:
                break
        return jsonify(out), 200
    except Exception:
        return jsonify([]), 200


# ── POST /watchlist ───────────────────────────────────────────────────────────

@app.route("/watchlist", methods=["POST", "OPTIONS"])
def add_symbol():
    if request.method == "OPTIONS":
        return jsonify({}), 200

    body   = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").strip().upper()

    if not symbol:
        return jsonify({"error": "Symbol is required."}), 400

    # Validate ticker
    validation = md.validate_ticker(symbol)
    if not validation["valid"]:
        return jsonify({"error": validation["error"]}), 400

    # Check duplicate
    if db.symbol_exists(symbol):
        return jsonify({"error": f"{symbol} is already in your watchlist."}), 409

    # Fetch initial data for first snapshot
    data = md.fetch_stock_data(symbol)

    ewma_volatility = vol.DEFAULT_VOLATILITY
    avg_volume_20d  = data.get("avg_volume_20d") or 0.0
    used_fallback   = True

    if data["status"] == "ok" and data["history_df"] is not None:
        ewma_volatility, used_fallback = vol.compute_ewma_volatility(data["history_df"])
        avg_volume_20d  = data.get("avg_volume_20d") or 0.0

    price  = data.get("price")  or 0.0
    volume = data.get("volume") or 0

    db.add_to_watchlist(symbol)
    db.insert_snapshot(symbol, price, volume, ewma_volatility, avg_volume_20d)

    return jsonify({
        "symbol":          symbol,
        "status":          "added",
        "first_visit":     True,
        "price":           price,
        "volatility_class": vol.classify_volatility(ewma_volatility),
        "used_fallback_vol": used_fallback,
        "data_status":     data["status"],
    }), 201


# ── DELETE /watchlist/<symbol> ────────────────────────────────────────────────

@app.route("/watchlist/<symbol>", methods=["DELETE", "OPTIONS"])
def remove_symbol(symbol):
    if request.method == "OPTIONS":
        return jsonify({}), 200
    symbol = symbol.upper()
    if not db.symbol_exists(symbol):
        return jsonify({"error": f"{symbol} not found in watchlist."}), 404
    db.remove_from_watchlist(symbol)
    return jsonify({"symbol": symbol, "status": "removed"}), 200


# ── GET /watchlist ────────────────────────────────────────────────────────────

@app.route("/watchlist", methods=["GET"])
def get_watchlist():
    symbols = db.get_all_symbols()
    if not symbols:
        db.set_last_visit_time()
        return jsonify([]), 200

    results = []
    with ThreadPoolExecutor(max_workers=min(len(symbols), 8)) as executor:
        future_map = {executor.submit(_process_symbol, s): s for s in symbols}
        for future in as_completed(future_map):
            try:
                results.append(future.result())
            except Exception as e:
                results.append(_error_item(future_map[future], str(e)))

    def sort_key(item):
        if item.get("data_status") in ("unavailable", "halted"):
            return (2, 0)
        if item.get("first_visit"):
            return (1, 0)
        return (0, -(item.get("change_score") or 0))

    results.sort(key=sort_key)
    db.set_last_visit_time()
    return jsonify(results), 200


# ── GET /last-visit ───────────────────────────────────────────────────────────

@app.route("/last-visit", methods=["GET"])
def last_visit():
    ts = db.get_last_visit_time()
    return jsonify({"last_visit_time": ts}), 200


# ── GET /history/<symbol> ─────────────────────────────────────────────────────

@app.route("/history/<symbol>", methods=["GET"])
def get_history(symbol):
    symbol = symbol.upper()
    if not db.symbol_exists(symbol):
        return jsonify({"error": f"{symbol} not in watchlist"}), 404
    snaps = db.get_all_snapshots(symbol)
    return jsonify({"symbol": symbol, "snapshots": snaps}), 200


# ── Internal: process one symbol ──────────────────────────────────────────────

def _process_symbol(symbol: str) -> dict:
    last_snap = db.get_last_seen_snapshot(symbol)
    data      = md.fetch_stock_data(symbol)

    # ── Unavailable ──
    if data["status"] == "unavailable":
        reason = ce.generate_reason_string(
            symbol, "unavailable", None, None,
            last_updated=last_snap["taken_at"] if last_snap else None,
        )
        return {
            "symbol": symbol, "price": last_snap["price"] if last_snap else None,
            "change_score": None, "is_meaningful": False, "reason": reason,
            "data_status": "unavailable", "volatility_class": None, "vol_trend": None,
            "ewma_volatility": None, "pct_of_52w_range": None, "sparkline": [],
            "direction": None, "crossed_52w_high": False, "crossed_52w_low": False,
            "first_visit": last_snap is None,
            "last_updated": last_snap["taken_at"] if last_snap else None,
            "week52_high": None, "week52_low": None,
        }

    # ── Volatility ──
    ewma_volatility, used_fallback = vol.DEFAULT_VOLATILITY, True
    avg_volume_20d  = data.get("avg_volume_20d") or 0.0
    if data["history_df"] is not None:
        ewma_volatility, used_fallback = vol.compute_ewma_volatility(data["history_df"])
        avg_volume_20d  = data.get("avg_volume_20d") or avg_volume_20d

    volatility_class = vol.classify_volatility(ewma_volatility)
    vol_trend        = vol.compute_volatility_trend(data["history_df"])

    # ── Halted ──
    if data["status"] == "halted":
        db.insert_snapshot(symbol, data["price"], data.get("volume") or 0,
                           ewma_volatility, avg_volume_20d)
        level_result = ce.check_52w_levels(
            data["price"], last_snap["price"] if last_snap else data["price"],
            data.get("week52_high"), data.get("week52_low"))
        return {
            "symbol": symbol, "price": data["price"],
            "change_score": 999.0, "is_meaningful": True,
            "reason": ce.generate_reason_string(symbol, "halted", None, None),
            "data_status": "halted", "volatility_class": volatility_class,
            "vol_trend": vol_trend, "ewma_volatility": round(ewma_volatility*100, 3),
            "pct_of_52w_range": level_result.get("pct_of_52w_range"),
            "sparkline": data.get("sparkline", []), "direction": "flat",
            "crossed_52w_high": level_result.get("crossed_52w_high", False),
            "crossed_52w_low":  level_result.get("crossed_52w_low",  False),
            "first_visit": last_snap is None, "last_updated": data["timestamp"],
            "week52_high": data.get("week52_high"), "week52_low": data.get("week52_low"),
        }

    current_price  = data["price"]
    current_volume = data.get("volume")

    # ── First visit ──
    if last_snap is None:
        db.insert_snapshot(symbol, current_price, current_volume or 0,
                           ewma_volatility, avg_volume_20d)
        level_result = ce.check_52w_levels(
            current_price, current_price,
            data.get("week52_high"), data.get("week52_low"))
        return {
            "symbol": symbol, "price": current_price,
            "change_score": None, "is_meaningful": False,
            "reason": ce.generate_reason_string(symbol, "first_visit", None, None, used_fallback),
            "data_status": "ok", "volatility_class": volatility_class,
            "vol_trend": vol_trend, "ewma_volatility": round(ewma_volatility*100, 3),
            "pct_of_52w_range": level_result.get("pct_of_52w_range"),
            "sparkline": data.get("sparkline", []), "direction": None,
            "crossed_52w_high": False, "crossed_52w_low": False,
            "first_visit": True, "last_updated": data["timestamp"],
            "week52_high": data.get("week52_high"), "week52_low": data.get("week52_low"),
        }

    # ── Normal comparison ──
    last_price    = last_snap["price"]
    change_result = ce.compute_change_score(
        current_price, last_price, ewma_volatility, current_volume, avg_volume_20d)
    level_result  = ce.check_52w_levels(
        current_price, last_price,
        data.get("week52_high"), data.get("week52_low"))

    score = change_result["score"]
    if level_result["crossed_52w_high"] or level_result["crossed_52w_low"]:
        score = max(score, 2.5)
        change_result["is_meaningful"] = True

    reason = ce.generate_reason_string(
        symbol, "ok", change_result, level_result, used_fallback)

    db.insert_snapshot(symbol, current_price, current_volume or 0,
                       ewma_volatility, avg_volume_20d)

    return {
        "symbol": symbol, "price": current_price,
        "change_score": round(score, 4),
        "is_meaningful": change_result["is_meaningful"],
        "reason": reason,
        "data_status": data["status"],
        "volatility_class": volatility_class,
        "vol_trend": vol_trend,
        "ewma_volatility": round(ewma_volatility * 100, 3),
        "pct_of_52w_range": level_result.get("pct_of_52w_range"),
        "sparkline": data.get("sparkline", []),
        "direction": change_result["direction"],
        "crossed_52w_high": level_result.get("crossed_52w_high", False),
        "crossed_52w_low":  level_result.get("crossed_52w_low",  False),
        "first_visit": False,
        "last_updated": data["timestamp"],
        "week52_high": data.get("week52_high"),
        "week52_low":  data.get("week52_low"),
        "price_move_pct":   change_result.get("price_move_pct"),
        "volatility_ratio": change_result.get("volatility_ratio"),
        "volume_ratio":     change_result.get("volume_ratio"),
    }


def _error_item(symbol: str, error: str) -> dict:
    last_snap = db.get_last_seen_snapshot(symbol)
    return {
        "symbol": symbol, "price": last_snap["price"] if last_snap else None,
        "change_score": None, "is_meaningful": False,
        "reason": f"{symbol} — fetch failed: {error}",
        "data_status": "unavailable", "volatility_class": None,
        "vol_trend": None, "ewma_volatility": None,
        "pct_of_52w_range": None, "sparkline": [], "direction": None,
        "crossed_52w_high": False, "crossed_52w_low": False,
        "first_visit": last_snap is None,
        "last_updated": last_snap["taken_at"] if last_snap else None,
        "week52_high": None, "week52_low": None,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    print("Smart Market Watchlist running at http://localhost:5000")
    app.run(debug=True, host="0.0.0.0", port=5000)
