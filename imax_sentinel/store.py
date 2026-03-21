"""
store.py — SQLite state store for IMAX Sentinel

Tracks every performance we've seen and its last-known status.
Change detection is purely: has context_id been seen before,
and has its status changed since we last saw it?
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/sentinel.db"

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS performances (
    context_id      TEXT PRIMARY KEY,   -- AudienceView performance UUID
    article_id      TEXT NOT NULL,      -- AudienceView film UUID
    title           TEXT NOT NULL,
    datetime_str    TEXT NOT NULL,
    venue           TEXT NOT NULL,
    status          TEXT NOT NULL,      -- available | soldout | unavailable
    booking_url     TEXT NOT NULL,
    source_url      TEXT NOT NULL,      -- which listing page surfaced this
    first_seen_at   TEXT NOT NULL,      -- ISO datetime
    last_seen_at    TEXT NOT NULL,      -- ISO datetime
    last_status_at  TEXT NOT NULL       -- ISO datetime of last status change
);

CREATE TABLE IF NOT EXISTS status_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id      TEXT NOT NULL,
    old_status      TEXT NOT NULL,
    new_status      TEXT NOT NULL,
    changed_at      TEXT NOT NULL       -- ISO datetime
);
"""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


@contextmanager
def _connect(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create tables if they don't exist yet."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(_DDL)
    logger.info("Database ready: %s", db_path)


def upsert_performance(
    *,
    context_id: str,
    article_id: str,
    title: str,
    datetime_str: str,
    venue: str,
    status: str,
    booking_url: str,
    source_url: str,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    """
    Insert or update a performance row.

    Returns a dict describing what changed:
      {
        "is_new":         bool,   # first time we've seen this context_id
        "status_changed": bool,   # status is different from last time
        "old_status":     str,    # previous status (empty string if new)
        "new_status":     str,
      }
    """
    now = datetime.utcnow().isoformat()

    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT status, first_seen_at FROM performances WHERE context_id = ?",
            (context_id,),
        ).fetchone()

        if existing is None:
            # Brand new performance
            conn.execute(
                """
                INSERT INTO performances
                    (context_id, article_id, title, datetime_str, venue,
                     status, booking_url, source_url,
                     first_seen_at, last_seen_at, last_status_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    context_id,
                    article_id,
                    title,
                    datetime_str,
                    venue,
                    status,
                    booking_url,
                    source_url,
                    now,
                    now,
                    now,
                ),
            )
            logger.debug("New performance stored: %s (%s)", title, context_id)
            return {"is_new": True, "status_changed": False, "old_status": "", "new_status": status}

        old_status = existing["status"]
        status_changed = old_status != status

        conn.execute(
            """
            UPDATE performances
               SET status         = ?,
                   booking_url    = ?,
                   last_seen_at   = ?,
                   last_status_at = CASE WHEN status != ? THEN ? ELSE last_status_at END
             WHERE context_id = ?
            """,
            (status, booking_url, now, status, now, context_id),
        )

        if status_changed:
            conn.execute(
                """
                INSERT INTO status_history (context_id, old_status, new_status, changed_at)
                VALUES (?,?,?,?)
                """,
                (context_id, old_status, status, now),
            )
            logger.info(
                "Status changed: %r  %s → %s  (%s)",
                title,
                old_status,
                status,
                context_id,
            )

        return {
            "is_new": False,
            "status_changed": status_changed,
            "old_status": old_status,
            "new_status": status,
        }


def get_performance(context_id: str, db_path: str = DEFAULT_DB_PATH) -> dict | None:
    """Fetch a single performance row by context_id."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM performances WHERE context_id = ?", (context_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_performances(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Return all tracked performances ordered by title then datetime."""
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM performances ORDER BY title, datetime_str").fetchall()
        return [dict(r) for r in rows]


def get_status_history(context_id: str, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Return the full status history for a performance."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM status_history WHERE context_id = ? ORDER BY changed_at",
            (context_id,),
        ).fetchall()
        return [dict(r) for r in rows]
