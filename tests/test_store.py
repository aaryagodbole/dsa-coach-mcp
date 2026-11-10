from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fsrs import Card, Rating

from dsa_coach_mcp.models import Mistake, Problem
from dsa_coach_mcp.store import ReviewStore

AT = datetime(2026, 1, 1, 9, tzinfo=UTC)


def problem(problem_id: str, tags: list[str] | None = None) -> Problem:
    return Problem(
        platform="leetcode",
        problem_id=problem_id,
        title=problem_id,
        url=f"https://example.com/{problem_id}",
        tags=tags or [],
    )


def due_in(days: int) -> Card:
    return Card(due=AT + timedelta(days=days))


def test_a_review_round_trips_with_its_log(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    store.record_review(problem("two-sum"), due_in(2), Rating.Good, AT, [])
    store.record_review(problem("two-sum"), due_in(9), Rating.Easy, AT + timedelta(days=2), [])

    record = store.get("leetcode", "two-sum")

    assert record is not None
    assert record.card.due == AT + timedelta(days=9)
    assert record.reviews == 2
    assert [log.rating for log in store.review_logs()] == [Rating.Good, Rating.Easy]
    assert store.get("leetcode", "missing") is None


def test_due_lists_overdue_first_and_skips_future(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    store.record_review(problem("later"), due_in(10), Rating.Good, AT, [])
    store.record_review(problem("today"), due_in(4), Rating.Good, AT, [])
    store.record_review(problem("overdue"), due_in(1), Rating.Good, AT, [])

    due = store.due(AT + timedelta(days=4))

    assert [r.problem_id for r in due] == ["overdue", "today"]


def test_parameters_are_saved_and_replaced(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    assert store.parameters() is None

    store.save_parameters([0.1, 0.2])
    store.save_parameters([0.3])

    assert store.parameters() == [0.3]


def test_an_sm2_database_moves_to_fsrs_keeping_cards_and_mistakes(tmp_path: Path) -> None:
    path = tmp_path / "coach.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE review_cards (platform TEXT NOT NULL, problem_id TEXT NOT NULL, "
            "title TEXT NOT NULL, url TEXT NOT NULL, ease REAL NOT NULL, "
            "interval_days INTEGER NOT NULL, repetitions INTEGER NOT NULL, "
            "due TEXT NOT NULL, PRIMARY KEY (platform, problem_id));"
            "CREATE TABLE mistakes (id INTEGER PRIMARY KEY, platform TEXT NOT NULL, "
            "problem_id TEXT NOT NULL, tags TEXT NOT NULL, kind TEXT NOT NULL, "
            "note TEXT NOT NULL, logged_on TEXT NOT NULL);"
            "INSERT INTO review_cards VALUES ('leetcode', 'two-sum', 'Two Sum', "
            "'https://example.com/two-sum', 2.5, 6, 2, '2026-01-05');"
            "INSERT INTO mistakes VALUES (1, 'leetcode', 'two-sum', '[\"array\"]', "
            "'off by one', 'loop bound', '2025-12-30');"
            "PRAGMA user_version = 2;"
        )

    store = ReviewStore(path)
    record = store.get("leetcode", "two-sum")

    assert record is not None
    assert (record.title, record.card.due) == ("Two Sum", datetime(2026, 1, 5, tzinfo=UTC))
    assert [m.note for m in store.mistakes(limit=10)] == ["loop bound"]
    # Cards from before tags were stored take them from the mistakes logged on them.
    assert [h.tags for h in store.histories()] == [["array"]]


# 0: databases written before the schema was versioned; 1: after its first migration.
@pytest.mark.parametrize("user_version", [0, 1])
def test_a_first_version_database_upgrades_all_the_way(tmp_path: Path, user_version: int) -> None:
    path = tmp_path / "coach.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE review_cards (platform TEXT NOT NULL, problem_id TEXT NOT NULL, "
            "title TEXT NOT NULL, url TEXT NOT NULL, ease REAL NOT NULL, "
            "interval_days INTEGER NOT NULL, repetitions INTEGER NOT NULL, "
            "due TEXT NOT NULL, PRIMARY KEY (platform, problem_id));"
            "INSERT INTO review_cards VALUES ('leetcode', 'two-sum', 'Two Sum', "
            "'https://example.com/two-sum', 2.5, 1, 1, '2026-01-02');"
            f"PRAGMA user_version = {user_version};"
        )

    store = ReviewStore(path)
    # Checked before any review: record_review would recreate a card the migration lost.
    migrated = store.get("leetcode", "two-sum")
    assert migrated is not None
    assert (migrated.title, migrated.card.due) == ("Two Sum", datetime(2026, 1, 2, tzinfo=UTC))

    store.record_review(
        problem("two-sum", ["array"]),
        due_in(3),
        Rating.Hard,
        AT,
        [Mistake(kind="off by one", note="loop bound")],
    )

    assert [k.kind for k in store.mistake_kinds()] == ["off by one"]
    assert ReviewStore(path).get("leetcode", "two-sum") is not None


def test_patterns_and_kinds_respect_since(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    old, recent = AT, AT + timedelta(days=59)
    store.record_review(
        problem("a", ["dp"]), due_in(1), Rating.Again, old, [Mistake(kind="k", note="old")]
    )
    store.record_review(
        problem("b", ["graph"]), due_in(61), Rating.Again, recent, [Mistake(kind="k", note="new")]
    )

    patterns = store.patterns(since=recent.date() - timedelta(days=1))

    assert [(k.kind, k.count) for k in patterns.kinds] == [("k", 1)]
    assert [(c.key, c.count) for c in patterns.by_tag] == [("graph", 1)]
    assert [(c.key, c.count) for c in patterns.by_month] == [("2026-03", 1)]
    assert [m.note for m in store.mistakes(tag="dp", limit=10)] == ["old"]
    assert store.mistakes(since=date(2027, 1, 1), limit=10) == []


def test_patterns_count_every_tag_by_name_not_by_position(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    mistake = [Mistake(kind="missed cycle", note="n")]
    store.record_review(problem("a", ["graph", "bfs"]), due_in(1), Rating.Hard, AT, mistake)
    store.record_review(problem("b", ["dfs", "graph"]), due_in(1), Rating.Hard, AT, mistake)

    counts = {c.key: c.count for c in store.patterns().by_tag}

    assert counts == {"graph": 2, "bfs": 1, "dfs": 1}


def test_histories_keep_reviews_mistakes_and_latest_tags_per_card(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    store.record_review(problem("a", ["graph"]), due_in(2), Rating.Hard, AT, [])
    store.record_review(
        problem("a", ["graph", "bfs"]),
        due_in(5),
        Rating.Again,
        AT + timedelta(days=2),
        [Mistake(kind="missed cycle", note="no visited set")],
    )
    store.record_review(problem("b"), due_in(1), Rating.Good, AT, [])

    a, b = store.histories()

    assert a.tags == ["graph", "bfs"]
    assert [r for r, _ in a.reviews] == [Rating.Hard, Rating.Again]
    assert a.mistakes == [("missed cycle", (AT + timedelta(days=2)).date())]
    assert (b.tags, len(b.reviews), b.mistakes) == ([], 1, [])


def test_accounts_are_linked_replaced_and_unlinked(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")

    store.link_account("leetcode", "alice", AT)
    store.link_account("codeforces", "tourist", AT)
    store.link_account("leetcode", "bob", AT)

    assert store.accounts() == [("codeforces", "tourist"), ("leetcode", "bob")]
    assert store.unlink_account("leetcode") is True
    assert store.unlink_account("leetcode") is False
    assert ReviewStore(tmp_path / "coach.db").accounts() == [("codeforces", "tourist")]


def test_mistakes_by_tag_counts_each_kind_and_keeps_the_latest_note(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    store.record_review(
        problem("p1", ["graph", "bfs"]),
        due_in(3),
        Rating.Hard,
        AT,
        [Mistake(kind="missed cycle", note="old note")],
    )
    later = AT + timedelta(days=2)
    store.record_review(
        problem("p2", ["graph"]),
        due_in(3),
        Rating.Hard,
        later,
        [Mistake(kind="missed cycle", note="new note")],
    )

    rows = {(tag, kind): (n, last, note) for tag, kind, n, last, note in store.mistakes_by_tag()}

    assert rows[("graph", "missed cycle")] == (2, later.date(), "new note")
    assert rows[("bfs", "missed cycle")] == (1, AT.date(), "old note")
