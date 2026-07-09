"""SQLite persistence: schema init and all CRUD access.

Single shared connection (SQLite + a single asyncio event loop means no real
concurrency to worry about here) opened lazily via get_connection().
"""
import os
import sqlite3
import uuid
from datetime import datetime, timezone

import config
from models import WatchlistEntry

MAX_WATCHLIST_PER_USER = 5
VALID_FREQUENCIES = (1, 2, 3, 6, 12, 24)
PENDING_SUMMARY_TTL_DAYS = 7

_connection: sqlite3.Connection | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        path = config.get_database_path()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        _connection = sqlite3.connect(path, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA foreign_keys = ON")
        _init_schema(_connection)
    return _connection


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS cik_cache (
            ticker        TEXT PRIMARY KEY,
            cik           TEXT NOT NULL,
            company_name  TEXT,
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id                 INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            ticker                  TEXT NOT NULL,
            cik                     TEXT NOT NULL,
            frequency_hours         INTEGER NOT NULL DEFAULT 6
                                        CHECK (frequency_hours IN (1,2,3,6,12,24)),
            last_checked_at         TEXT,
            last_seen_accession_no  TEXT,
            created_at              TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (user_id, ticker)
        );
        CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
        CREATE INDEX IF NOT EXISTS idx_watchlist_cik ON watchlist(cik);
        CREATE INDEX IF NOT EXISTS idx_watchlist_freq ON watchlist(frequency_hours);

        CREATE TABLE IF NOT EXISTS pending_summaries (
            summary_id   TEXT PRIMARY KEY,
            ticker       TEXT NOT NULL,
            cik          TEXT NOT NULL,
            accession_no TEXT NOT NULL,
            filing_url   TEXT NOT NULL,
            form_type    TEXT NOT NULL,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS robostrategy_snapshot (
            id              INTEGER PRIMARY KEY CHECK (id = 1),
            as_of           TEXT,
            nav_per_share   REAL,
            holdings_json   TEXT NOT NULL,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS robostrategy_pending_ai (
            summary_id  TEXT PRIMARY KEY,
            diff_text   TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    # ALTER TABLE ... ADD COLUMN doesn't have an IF NOT EXISTS form, and CREATE TABLE IF NOT
    # EXISTS above is a no-op against an already-initialized users table (this bot is already
    # running in production with a persistent data/bot.db) -- check first, add if missing.
    _ensure_column(conn, "users", "robostrategy_enabled", "robostrategy_enabled INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, add_column_ddl: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {add_column_ddl}")


# --- users ---------------------------------------------------------------

def upsert_user(user_id: int) -> None:
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()


# --- cik cache -------------------------------------------------------------

def get_cached_cik(ticker: str) -> sqlite3.Row | None:
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM cik_cache WHERE ticker = ?", (ticker.upper(),)
    ).fetchone()


def upsert_cik(ticker: str, cik: str, company_name: str | None) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO cik_cache (ticker, cik, company_name, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET cik=excluded.cik,
            company_name=excluded.company_name, updated_at=excluded.updated_at
        """,
        (ticker.upper(), cik, company_name, _now_iso()),
    )
    conn.commit()


# --- watchlist ---------------------------------------------------------------

def _row_to_entry(row: sqlite3.Row) -> WatchlistEntry:
    return WatchlistEntry(
        id=row["id"],
        user_id=row["user_id"],
        ticker=row["ticker"],
        cik=row["cik"],
        frequency_hours=row["frequency_hours"],
        last_checked_at=row["last_checked_at"],
        last_seen_accession_no=row["last_seen_accession_no"],
    )


def count_watchlist(user_id: int) -> int:
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM watchlist WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row["n"]


def get_watchlist_entry(user_id: int, ticker: str) -> WatchlistEntry | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM watchlist WHERE user_id = ? AND ticker = ?",
        (user_id, ticker.upper()),
    ).fetchone()
    return _row_to_entry(row) if row else None


def get_watchlist_for_user(user_id: int) -> list[WatchlistEntry]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM watchlist WHERE user_id = ? ORDER BY ticker", (user_id,)
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def get_watchlist_rows_by_frequency(frequency_hours: int) -> list[WatchlistEntry]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM watchlist WHERE frequency_hours = ?", (frequency_hours,)
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def add_watchlist_entry(
    user_id: int,
    ticker: str,
    cik: str,
    frequency_hours: int = 6,
    last_seen_accession_no: str | None = None,
) -> WatchlistEntry:
    conn = get_connection()
    cur = conn.execute(
        """
        INSERT INTO watchlist (user_id, ticker, cik, frequency_hours, last_seen_accession_no)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, ticker.upper(), cik, frequency_hours, last_seen_accession_no),
    )
    conn.commit()
    entry_id = cur.lastrowid
    row = conn.execute("SELECT * FROM watchlist WHERE id = ?", (entry_id,)).fetchone()
    return _row_to_entry(row)


def remove_watchlist_entry(user_id: int, ticker: str) -> bool:
    conn = get_connection()
    cur = conn.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
        (user_id, ticker.upper()),
    )
    conn.commit()
    return cur.rowcount > 0


def set_frequency(user_id: int, ticker: str, frequency_hours: int) -> bool:
    conn = get_connection()
    cur = conn.execute(
        "UPDATE watchlist SET frequency_hours = ? WHERE user_id = ? AND ticker = ?",
        (frequency_hours, user_id, ticker.upper()),
    )
    conn.commit()
    return cur.rowcount > 0


def update_watchlist_checkpoint(
    entry_id: int, accession_no: str | None, checked_at: str
) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE watchlist SET last_seen_accession_no = ?, last_checked_at = ? WHERE id = ?",
        (accession_no, checked_at, entry_id),
    )
    conn.commit()


# --- pending AI-summary requests -----------------------------------------

def insert_pending_summary(
    ticker: str, cik: str, accession_no: str, filing_url: str, form_type: str
) -> str:
    summary_id = uuid.uuid4().hex[:12]
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO pending_summaries (summary_id, ticker, cik, accession_no, filing_url, form_type)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (summary_id, ticker, cik, accession_no, filing_url, form_type),
    )
    conn.commit()
    return summary_id


def get_pending_summary(summary_id: str) -> sqlite3.Row | None:
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM pending_summaries WHERE summary_id = ?", (summary_id,)
    ).fetchone()


def prune_old_pending_summaries() -> None:
    conn = get_connection()
    conn.execute(
        f"DELETE FROM pending_summaries WHERE created_at < datetime('now', '-{PENDING_SUMMARY_TTL_DAYS} days')"
    )
    conn.commit()


# --- RoboStrategy portfolio monitor ---------------------------------------

def get_robostrategy_subscribers() -> list[int]:
    conn = get_connection()
    rows = conn.execute("SELECT user_id FROM users WHERE robostrategy_enabled = 1").fetchall()
    return [row["user_id"] for row in rows]


def is_robostrategy_enabled(user_id: int) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT robostrategy_enabled FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    return bool(row["robostrategy_enabled"]) if row else False


def set_robostrategy_enabled(user_id: int, enabled: bool) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE users SET robostrategy_enabled = ? WHERE user_id = ?",
        (1 if enabled else 0, user_id),
    )
    conn.commit()


def get_robostrategy_snapshot() -> sqlite3.Row | None:
    conn = get_connection()
    return conn.execute("SELECT * FROM robostrategy_snapshot WHERE id = 1").fetchone()


def save_robostrategy_snapshot(as_of: str | None, nav_per_share: float | None, holdings_json: str) -> None:
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO robostrategy_snapshot (id, as_of, nav_per_share, holdings_json, updated_at)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET as_of=excluded.as_of, nav_per_share=excluded.nav_per_share,
            holdings_json=excluded.holdings_json, updated_at=excluded.updated_at
        """,
        (as_of, nav_per_share, holdings_json, _now_iso()),
    )
    conn.commit()


# --- pending AI-narration requests (RoboStrategy diffs) --------------------

def insert_robostrategy_pending_ai(diff_text: str) -> str:
    summary_id = uuid.uuid4().hex[:12]
    conn = get_connection()
    conn.execute(
        "INSERT INTO robostrategy_pending_ai (summary_id, diff_text) VALUES (?, ?)",
        (summary_id, diff_text),
    )
    conn.commit()
    return summary_id


def get_robostrategy_pending_ai(summary_id: str) -> sqlite3.Row | None:
    conn = get_connection()
    return conn.execute(
        "SELECT * FROM robostrategy_pending_ai WHERE summary_id = ?", (summary_id,)
    ).fetchone()


def prune_old_robostrategy_pending_ai() -> None:
    conn = get_connection()
    conn.execute(
        f"DELETE FROM robostrategy_pending_ai WHERE created_at < datetime('now', '-{PENDING_SUMMARY_TTL_DAYS} days')"
    )
    conn.commit()
