"""Local SQLite store for review cards, review history and the mistake journal."""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from fsrs import Card, Rating, ReviewLog

from .models import (
    Mistake,
    MistakeCount,
    MistakeEntry,
    MistakeKind,
    MistakePatterns,
    Problem,
)

DB_PATH_ENV = "DSA_COACH_DB"
DEFAULT_DB_PATH = Path.home() / ".dsa-coach" / "coach.db"


@dataclass(frozen=True)
class CardRecord:
    platform: str
    problem_id: str
    title: str
    url: str
    card: Card
    reviews: int


def _move_to_fsrs(conn: sqlite3.Connection) -> None:
    """Version 3: SM-2 cards become FSRS cards, reviews are logged one by one, and
    mistakes point at the new cards.

    SM-2's ease and interval cannot be translated into FSRS memory state, so each card
    keeps its due date and starts FSRS afresh at its next review."""

    conn.executescript(
        """
        CREATE TABLE cards (
            id         INTEGER PRIMARY KEY,
            platform   TEXT NOT NULL,
            problem_id TEXT NOT NULL,
            title      TEXT NOT NULL,
            url        TEXT NOT NULL,
            fsrs       TEXT NOT NULL,
            due        TEXT NOT NULL,
            UNIQUE (platform, problem_id)
        );
        CREATE INDEX cards_due ON cards (due);
        CREATE TABLE reviews (
            id          INTEGER PRIMARY KEY,
            card_id     INTEGER NOT NULL REFERENCES cards (id),
            rating      INTEGER NOT NULL,
            reviewed_at TEXT    NOT NULL
        );
        CREATE INDEX reviews_card ON reviews (card_id);
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    old = conn.execute("SELECT platform, problem_id, title, url, due FROM review_cards")
    for row in old.fetchall():
        due = datetime.combine(date.fromisoformat(row[4]), datetime.min.time(), tzinfo=UTC)
        conn.execute(
            "INSERT INTO cards (platform, problem_id, title, url, fsrs, due) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (*row[:4], Card(due=due).to_json(), due.isoformat()),
        )
    conn.executescript(
        """
        CREATE TABLE mistakes_v3 (
            id         INTEGER PRIMARY KEY,
            platform   TEXT NOT NULL,
            problem_id TEXT NOT NULL,
            tags       TEXT NOT NULL,
            kind       TEXT NOT NULL,
            note       TEXT NOT NULL,
            logged_on  TEXT NOT NULL,
            FOREIGN KEY (platform, problem_id) REFERENCES cards (platform, problem_id)
        );
        INSERT INTO mistakes_v3 SELECT * FROM mistakes;
        DROP TABLE mistakes;
        ALTER TABLE mistakes_v3 RENAME TO mistakes;
        CREATE INDEX mistakes_kind ON mistakes (kind);
        CREATE INDEX mistakes_logged_on ON mistakes (logged_on);
        DROP TABLE review_cards;
        """
    )


# Applied in order; the database's user_version records how many have run.
_MIGRATIONS: tuple[str | Callable[[sqlite3.Connection], None], ...] = (
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
    _move_to_fsrs,
    """
    CREATE TABLE problems (
        platform   TEXT NOT NULL,
        problem_id TEXT NOT NULL,
        title      TEXT NOT NULL,
        url        TEXT NOT NULL UNIQUE,
        tags       TEXT NOT NULL,
        level      TEXT,
        PRIMARY KEY (platform, problem_id)
    );
    """,
)

_PARAMETERS_KEY = "fsrs_parameters"
_RECORD_SQL = (
    "SELECT c.platform, c.problem_id, c.title, c.url, c.fsrs, "
    "(SELECT COUNT(*) FROM reviews r WHERE r.card_id = c.id) AS reviews FROM cards c"
)


def default_db_path() -> Path:
    return Path(os.environ.get(DB_PATH_ENV) or DEFAULT_DB_PATH)


def _to_record(row: sqlite3.Row) -> CardRecord:
    return CardRecord(
        platform=row["platform"],
        problem_id=row["problem_id"],
        title=row["title"],
        url=row["url"],
        card=Card.from_json(row["fsrs"]),
        reviews=row["reviews"],
    )


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
        # Migrations rebuild tables, which foreign keys would block mid-way; they run
        # on their own connection with enforcement off, each in one transaction.
        conn = sqlite3.connect(path, autocommit=True)
        try:
            applied = conn.execute("PRAGMA user_version").fetchone()[0]
            for version, step in enumerate(_MIGRATIONS[applied:], start=applied + 1):
                conn.execute("BEGIN")
                try:
                    if callable(step):
                        step(conn)
                    else:
                        conn.executescript(step)
                    conn.execute(f"PRAGMA user_version = {version}")
                    conn.execute("COMMIT")
                except BaseException:
                    # SQLite may already have rolled back (disk full, I/O error); a
                    # failing ROLLBACK must not hide the error that caused it.
                    with suppress(sqlite3.Error):
                        conn.execute("ROLLBACK")
                    raise
        finally:
            conn.close()

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

    def get(self, platform: str, problem_id: str) -> CardRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                f"{_RECORD_SQL} WHERE c.platform = ? AND c.problem_id = ?",
                (platform, problem_id),
            ).fetchone()
        return _to_record(row) if row else None

    def record_review(
        self,
        problem: Problem,
        card: Card,
        rating: Rating,
        at: datetime,
        mistakes: Sequence[Mistake],
    ) -> None:
        """Save the rescheduled card, the review and the mistakes made on it in one
        transaction."""

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO cards (platform, problem_id, title, url, fsrs, due) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (platform, problem_id) DO UPDATE "
                "SET title = excluded.title, url = excluded.url, fsrs = excluded.fsrs, "
                "due = excluded.due",
                (
                    problem.platform,
                    problem.problem_id,
                    problem.title,
                    problem.url,
                    card.to_json(),
                    card.due.astimezone(UTC).isoformat(),
                ),
            )
            conn.execute(
                "INSERT INTO reviews (card_id, rating, reviewed_at) SELECT id, ?, ? FROM cards "
                "WHERE platform = ? AND problem_id = ?",
                (int(rating), at.astimezone(UTC).isoformat(), problem.platform, problem.problem_id),
            )
            conn.executemany(
                "INSERT INTO mistakes (platform, problem_id, tags, kind, note, logged_on) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        problem.platform,
                        problem.problem_id,
                        json.dumps(problem.tags),
                        m.kind,
                        m.note,
                        at.astimezone(UTC).date().isoformat(),
                    )
                    for m in mistakes
                ],
            )

    def due(self, at: datetime) -> list[CardRecord]:
        """Every card due by ``at``. One user's revision queue is small, and ranking it
        by recall needs all of it."""

        with self._connect() as conn:
            rows = conn.execute(
                f"{_RECORD_SQL} WHERE c.due <= ? ORDER BY c.due",
                (at.astimezone(UTC).isoformat(),),
            ).fetchall()
        return [_to_record(row) for row in rows]

    def review_logs(self) -> list[ReviewLog]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT card_id, rating, reviewed_at FROM reviews ORDER BY reviewed_at"
            ).fetchall()
        return [
            ReviewLog(
                card_id=row["card_id"],
                rating=Rating(row["rating"]),
                review_datetime=datetime.fromisoformat(row["reviewed_at"]),
                review_duration=None,
            )
            for row in rows
        ]

    def save_problem(self, problem: Problem) -> Problem:
        """Record a problem reported from a platform with no adapter. Recording the same
        problem again (even from a slightly different URL) updates it, and its review
        card, in one transaction."""

        with self._connect() as conn:
            conn.execute(
                "INSERT INTO problems (platform, problem_id, title, url, tags, level) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (platform, problem_id) DO UPDATE SET "
                "title = excluded.title, url = excluded.url, tags = excluded.tags, "
                "level = excluded.level",
                (
                    problem.platform,
                    problem.problem_id,
                    problem.title,
                    problem.url,
                    json.dumps(problem.tags),
                    problem.level,
                ),
            )
            conn.execute(
                "UPDATE cards SET title = ?, url = ? WHERE platform = ? AND problem_id = ?",
                (problem.title, problem.url, problem.platform, problem.problem_id),
            )
        found = self.problem(problem.platform, problem.problem_id)
        assert found is not None
        return found

    def problem(self, platform: str, problem_id: str) -> Problem | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT platform, problem_id, title, url, tags, level FROM problems "
                "WHERE platform = ? AND problem_id = ?",
                (platform, problem_id),
            ).fetchone()
        if row is None:
            return None
        return Problem(**{**dict(row), "tags": json.loads(row["tags"]), "source": "reported"})

    def reported_problems(self) -> list[Problem]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT platform, problem_id, title, url, tags, level FROM problems "
                "ORDER BY platform, problem_id"
            ).fetchall()
        return [
            Problem(**{**dict(row), "tags": json.loads(row["tags"]), "source": "reported"})
            for row in rows
        ]

    def progress(self, at: datetime) -> list[tuple[str, int, int, int]]:
        """Per platform: problems reviewed, reviews logged, and problems due now."""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.platform, COUNT(*) AS problems, "
                "SUM((SELECT COUNT(*) FROM reviews r WHERE r.card_id = c.id)) AS reviews, "
                "SUM(c.due <= ?) AS due_now FROM cards c GROUP BY c.platform "
                "ORDER BY c.platform",
                (at.astimezone(UTC).isoformat(),),
            ).fetchall()
        return [(r["platform"], r["problems"], r["reviews"], r["due_now"]) for r in rows]

    def parameters(self) -> list[float] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (_PARAMETERS_KEY,)
            ).fetchone()
        return list(json.loads(row["value"])) if row else None

    def save_parameters(self, parameters: Sequence[float]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (_PARAMETERS_KEY, json.dumps(list(parameters))),
            )

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
        problem_id: str | None = None,
        since: date | None = None,
        limit: int,
    ) -> list[MistakeEntry]:
        where, params = self._filters(
            kind=kind, tag=tag, platform=platform, problem_id=problem_id, since=since
        )
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT m.platform, m.problem_id, c.title, c.url, m.tags, m.kind, m.note, "
                "m.logged_on FROM mistakes m JOIN cards c "
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
                    # Not aliased "key": json_each has its own key column (the array
                    # index), which GROUP BY would pick instead of the alias.
                    f"SELECT m.kind AS kind, {key_sql} AS bucket, COUNT(*) AS count "
                    f"FROM {source} {where} GROUP BY m.kind, bucket "
                    "ORDER BY count DESC, kind, bucket",
                    params,
                ).fetchall()
                return [
                    MistakeCount(kind=row["kind"], key=row["bucket"], count=row["count"])
                    for row in rows
                ]

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
        problem_id: str | None = None,
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
        if problem_id is not None:
            clauses.append("m.problem_id = ?")
            params.append(problem_id)
        if since is not None:
            clauses.append("m.logged_on >= ?")
            params.append(since.isoformat())
        return ("WHERE " + " AND ".join(clauses) if clauses else ""), tuple(params)
