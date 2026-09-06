# Orbit — Signal-over-Noise Market Watchlist

A market watchlist that flags what's *actually* meaningful since your last visit — not flat % thresholds, but moves that are statistically unusual for that specific stock.

## Setup

**Prerequisites:** Python 3.9+

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`. The SQLite database is created automatically on first run.

## What it does

- Add/remove stocks from your watchlist
- Returns a ranked "since you left" digest instead of a flat price table
- Each stock's volatility baseline is computed individually (20-day EWMA), so a 2% move on a stable stock and a 2% move on a volatile one are judged differently
- Everything below the anomaly threshold collapses into a "Quiet" section

## Key design decisions

- **EWMA volatility baseline** (not a global % rule) — each stock's "normal" is learned from its own recent behavior; moves ≥1.5x that baseline are flagged
- **Global 60s TTL cache** on quote fetches — decouples user traffic from `yfinance` rate limits when many users watch the same symbol
- **Concurrent fetching** via `ThreadPoolExecutor` for multi-symbol watchlists
- **Vanilla JS/CSS frontend** — no build step, direct DOM updates; kept intentionally lightweight for a data-display use case
- **Edge cases handled explicitly:** market-closed detection (no false "quiet" signal on weekends/overnight), `auto_adjust=True` to avoid misreading stock splits as crashes, and repeated-identical-close detection as a proxy for trading halts

## Project structure

```
app.py                # Flask app, routes
db.py                  # Database schema and access
market_data.py          # yfinance wrapper + global quote cache
volatility.py            # EWMA volatility calculation
change_engine.py         # Change scoring + "since you left" reason strings
requirements.txt         # Python dependencies
index.html              # Watchlist + digest views
style.css               # Styling
app.js                  # Frontend logic, API calls, rendering
```
