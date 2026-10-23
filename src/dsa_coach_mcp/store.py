"""Local SQLite store for revision cards and the mistake journal."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from .models import (
    Mistake,
    MistakeCount,
    MistakeEntry,
    MistakeKind,
    MistakePatterns,
    ReviewCard,
)

DB_PATH_ENV = "DSA_COACH_DB"
DEFAULT_DB_PATH = Path.home() / ".dsa-coach" / "coach.db"

# Applied in order; the database's user_version records how many have run.
_MIGRATIONS: tuple[str, ...] = (
    """
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
    """,
    """
    CREATE TABLE mistakes (
        id         INTEGER PRIMARY KEY,
        platform   TEXT NOT NULL,
        problem_id TEXT NOT NULL,
        tags       TEXT NOT NULL,
        kind       TEXT NOT NULL,
        note       TEXT NOT NULL,
        logged_on  TEXT NOT NULL,
        FOREIGN KEY (platform, problem_id) REFERENCES review_cards (platform, problem_id)
    );
    CREATE INDEX mistakes_kind ON mistakes (kind);
    CREATE INDEX mistakes_logged_on ON mistakes (logged_on);
    """,
)

_CARD_COLUMNS = "platform, problem_id, title, url, ease, interval_days, repetitions, due"


def default_db_path() -> Path:
    return Path(os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH)


def _to_card(row: sqlite3.Row) -> ReviewCard:
    return ReviewCard(**{**dict(row), "due": date.fromisoformat(row["due"])})


def _to_entry(row: sqlite3.Row) -> MistakeEntry:
    return MistakeEntry(
        **{
            **dict(row),
            "tags": json.loads(row["tags"]),
            "logged_on": date.fromisoformat(row["logged_on"]),
        }
    )


class ReviewStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            applied = conn.execute("PRAGMA user_version").fetchone()[0]
            for version, script in enumerate(_MIGRATIONS[applied:], start=applied + 1):
                conn.executescript(f"BEGIN; {script} PRAGMA user_version = {version}; COMMIT;")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def _save_card(conn: sqlite3.Connection, card: ReviewCard) -> None:
        conn.execute(
            f"INSERT OR REPLACE INTO review_cards ({_CARD_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
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

    def get(self, platform: str, problem_id: str) -> ReviewCard | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_CARD_COLUMNS} FROM review_cards WHERE platform = ? AND problem_id = ?",
                (platform, problem_id),
            ).fetchone()
        return _to_card(row) if row else None

    def save(self, card: ReviewCard) -> None:
        with self._connect() as conn:
            self._save_card(conn, card)

    def record_review(
        self, card: ReviewCard, tags: Sequence[str], mistakes: Sequence[Mistake], on: date
    ) -> None:
        """Save the rescheduled card and the mistakes made on it in one transaction."""

        with self._connect() as conn:
            self._save_card(conn, card)
            conn.executemany(
                "INSERT INTO mistakes (platform, problem_id, tags, kind, note, logged_on) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        card.platform,
                        card.problem_id,
                        json.dumps(list(tags)),
                        m.kind,
                        m.note,
                        on.isoformat(),
                    )
                    for m in mistakes
                ],
            )

    def due(self, on: date, limit: int) -> list[ReviewCard]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_CARD_COLUMNS} FROM review_cards WHERE due <= ? ORDER BY due LIMIT ?",
                (on.isoformat(), limit),
            ).fetchall()
        return [_to_card(row) for row in rows]

    def mistake_kinds(self, since: date | None = None) -> list[MistakeKind]:
        where, params = self._filters(since=since)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT m.kind AS kind, COUNT(*) AS count, MAX(m.logged_on) AS last_seen "
                f"FROM mistakes m {where} GROUP BY m.kind ORDER BY count DESC, kind",
                params,
            ).fetchall()
        return [
            MistakeKind(
                kind=r["kind"], count=r["count"], last_seen=date.fromisoformat(r["last_seen"])
            )
            for r in rows
        ]

    def mistakes(
        self,
        *,
        kind: str | None = None,
        tag: str | None = None,
        platform: str | None = None,
        since: date | None = None,
        limit: int,
    ) -> list[MistakeEntry]:
        where, params = self._filters(kind=kind, tag=tag, platform=platform, since=since)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT m.platform, m.problem_id, c.title, c.url, m.tags, m.kind, m.note, "
                "m.logged_on FROM mistakes m JOIN review_cards c "
                "USING (platform, problem_id) "
                f"{where} ORDER BY m.logged_on DESC, m.id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [_to_entry(row) for row in rows]

    def patterns(self, since: date | None = None) -> MistakePatterns:
        where, params = self._filters(since=since)
        with self._connect() as conn:

            def counts(key_sql: str, source: str) -> list[MistakeCount]:
                rows = conn.execute(
                    f"SELECT m.kind AS kind, {key_sql} AS key, COUNT(*) AS count "
                    f"FROM {source} {where} GROUP BY m.kind, key ORDER BY count DESC, kind, key",
                    params,
                ).fetchall()
                return [MistakeCount(**dict(row)) for row in rows]

            by_tag = counts("t.value", "mistakes m, json_each(m.tags) t")
            by_platform = counts("m.platform", "mistakes m")
            by_month = counts("substr(m.logged_on, 1, 7)", "mistakes m")
        return MistakePatterns(
            kinds=self.mistake_kinds(since),
            by_tag=by_tag,
            by_platform=by_platform,
            by_month=by_month,
        )

    @staticmethod
    def _filters(
        *,
        kind: str | None = None,
        tag: str | None = None,
        platform: str | None = None,
        since: date | None = None,
    ) -> tuple[str, tuple[str, ...]]:
        clauses: list[str] = []
        params: list[str] = []
        if kind is not None:
            clauses.append("m.kind = ?")
            params.append(kind)
        if tag is not None:
            clauses.append("EXISTS (SELECT 1 FROM json_each(m.tags) WHERE value = ?)")
            params.append(tag)
        if platform is not None:
            clauses.append("m.platform = ?")
            params.append(platform)
        if since is not None:
            clauses.append("m.logged_on >= ?")
            params.append(since.isoformat())
        return ("WHERE " + " AND ".join(clauses) if clauses else ""), tuple(params)
