"""
db.py — SQLite database layer for Smart Market Watchlist
"""

import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "watchlist.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watchlist_items (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol     TEXT    NOT NULL UNIQUE,
                added_at   DATETIME NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol           TEXT    NOT NULL,
                price            REAL,
                volume           INTEGER,
                ewma_volatility  REAL,
                avg_volume_20d   REAL,
                taken_at         DATETIME NOT NULL DEFAULT (datetime('now')),
                is_last_seen     INTEGER  NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_snapshots_symbol ON snapshots(symbol);
            CREATE INDEX IF NOT EXISTS idx_snapshots_last_seen ON snapshots(symbol, is_last_seen);

            CREATE TABLE IF NOT EXISTS app_state (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
        """)


# ── Watchlist CRUD ──────────────────────────────────────────────────────────

def add_to_watchlist(symbol: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO watchlist_items (symbol, added_at) VALUES (?, datetime('now'))",
            (symbol.upper(),)
        )


def remove_from_watchlist(symbol: str):
    symbol = symbol.upper()
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist_items WHERE symbol = ?", (symbol,))
        conn.execute("DELETE FROM snapshots WHERE symbol = ?", (symbol,))


def get_all_symbols() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol FROM watchlist_items ORDER BY added_at ASC"
        ).fetchall()
    return [r["symbol"] for r in rows]


def symbol_exists(symbol: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM watchlist_items WHERE symbol = ?", (symbol.upper(),)
        ).fetchone()
    return row is not None


# ── Snapshots ───────────────────────────────────────────────────────────────

def get_last_seen_snapshot(symbol: str):
    with get_conn() as conn:
        row = conn.execute(
            """SELECT * FROM snapshots
               WHERE symbol = ? AND is_last_seen = 1
               ORDER BY taken_at DESC LIMIT 1""",
            (symbol.upper(),)
        ).fetchone()
    return dict(row) if row else None


def get_all_snapshots(symbol: str) -> list[dict]:
    """Returns all snapshots for a symbol ordered oldest-first (for charting)."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT price, ewma_volatility, avg_volume_20d, taken_at
               FROM snapshots
               WHERE symbol = ?
               ORDER BY taken_at ASC""",
            (symbol.upper(),)
        ).fetchall()
    return [dict(r) for r in rows]


def insert_snapshot(symbol: str, price: float, volume: int,
                    ewma_volatility: float, avg_volume_20d: float) -> int:
    """
    Atomically insert a new snapshot and flip is_last_seen to the new row.
    Returns the new snapshot id.
    """
    symbol = symbol.upper()
    with get_conn() as conn:
        # Unset old is_last_seen
        conn.execute(
            "UPDATE snapshots SET is_last_seen = 0 WHERE symbol = ?",
            (symbol,)
        )
        # Insert new snapshot as is_last_seen
        cur = conn.execute(
            """INSERT INTO snapshots
               (symbol, price, volume, ewma_volatility, avg_volume_20d, taken_at, is_last_seen)
               VALUES (?, ?, ?, ?, ?, datetime('now'), 1)""",
            (symbol, price, volume, ewma_volatility, avg_volume_20d)
        )
        return cur.lastrowid


# ── App State (last-visit tracking) ─────────────────────────────────────────

def get_last_visit_time() -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM app_state WHERE key = 'last_visit_time'"
        ).fetchone()
    return row["value"] if row else None


def set_last_visit_time():
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES ('last_visit_time', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (now,)
        )
