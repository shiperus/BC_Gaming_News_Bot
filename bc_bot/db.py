from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from rapidfuzz import fuzz, utils

SCHEMA = """
CREATE TABLE IF NOT EXISTS posted_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    posted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posted_at ON posted_items (posted_at);
"""

# Matches aggregator.CONSOLIDATION_THRESHOLD so a reworded restatement of an
# already-posted story is caught here just as reliably as duplicate titles are
# merged within a single cycle.
DUPLICATE_THRESHOLD = 80


class Store:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def recent_titles(self, retention_days: int) -> list[str]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT title FROM posted_items WHERE posted_at >= ?", (cutoff,)
            ).fetchall()
        return [row[0] for row in rows]

    def is_duplicate(self, title: str, retention_days: int) -> bool:
        for existing in self.recent_titles(retention_days):
            if (
                fuzz.token_sort_ratio(title, existing, processor=utils.default_process)
                >= DUPLICATE_THRESHOLD
            ):
                return True
        return False

    def record_posted(self, title: str, url: str, source: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO posted_items (title, url, source, posted_at) VALUES (?, ?, ?, ?)",
                (title, url, source, datetime.now(timezone.utc).isoformat()),
            )

    def cleanup_old(self, retention_days: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM posted_items WHERE posted_at < ?", (cutoff,))
            return cursor.rowcount
