from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('keyword', 'topic')),
    interval_minutes INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_run_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('verified', 'pending', 'suspicious')),
    relevance INTEGER NOT NULL,
    heat INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notified_at TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_group TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL,
    snippet TEXT NOT NULL,
    suspicious INTEGER NOT NULL DEFAULT 0,
    published_at TEXT,
    found_at TEXT NOT NULL,
    UNIQUE(event_id, source_url)
);
CREATE INDEX IF NOT EXISTS idx_events_rule ON events(rule_id, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_rule_url ON evidence(source_url, event_id);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    read_at TEXT,
    email_status TEXT NOT NULL,
    email_error TEXT,
    last_attempt_at TEXT
);
CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    error TEXT
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            evidence_columns = {row["name"] for row in connection.execute("PRAGMA table_info(evidence)")}
            if "suspicious" not in evidence_columns:
                connection.execute("ALTER TABLE evidence ADD COLUMN suspicious INTEGER NOT NULL DEFAULT 0")
            notification_columns = {row["name"] for row in connection.execute("PRAGMA table_info(notifications)")}
            if "last_attempt_at" not in notification_columns:
                connection.execute("ALTER TABLE notifications ADD COLUMN last_attempt_at TEXT")


def rows_to_dict(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]
