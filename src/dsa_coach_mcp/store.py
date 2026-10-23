"""Local SQLite store for revision cards."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from .models import ReviewCard

DB_PATH_ENV = "DSA_COACH_DB"
DEFAULT_DB_PATH = Path.home() / ".dsa-coach" / "coach.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_cards (
    platform      TEXT    NOT NULL,
    problem_id    TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    url           TEXT    NOT NULL,
    ease          REAL    NOT NULL,
    interval_days INTEGER NOT NULL,
    repetitions   INTEGER NOT NULL,
    due           TEXT    NOT NULL,
    PRIMARY KEY (platform, problem_id)
);
CREATE INDEX IF NOT EXISTS review_cards_due ON review_cards (due);
"""

_COLUMNS = "platform, problem_id, title, url, ease, interval_days, repetitions, due"


def default_db_path() -> Path:
    return Path(os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH)


def _to_card(row: sqlite3.Row) -> ReviewCard:
    return ReviewCard(**{**dict(row), "due": date.fromisoformat(row["due"])})


class ReviewStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get(self, platform: str, problem_id: str) -> ReviewCard | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM review_cards WHERE platform = ? AND problem_id = ?",
                (platform, problem_id),
            ).fetchone()
        return _to_card(row) if row else None

    def save(self, card: ReviewCard) -> None:
        with self._connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO review_cards ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    card.platform,
                    card.problem_id,
                    card.title,
                    card.url,
                    card.ease,
                    card.interval_days,
                    card.repetitions,
                    card.due.isoformat(),
                ),
            )

    def due(self, on: date, limit: int) -> list[ReviewCard]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM review_cards WHERE due <= ? ORDER BY due LIMIT ?",
                (on.isoformat(), limit),
            ).fetchall()
        return [_to_card(row) for row in rows]
