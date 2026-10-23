from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from dsa_coach_mcp.models import Mistake, ReviewCard
from dsa_coach_mcp.store import ReviewStore


def card(problem_id: str, due: date) -> ReviewCard:
    return ReviewCard(
        platform="leetcode",
        problem_id=problem_id,
        title=problem_id,
        url=f"https://example.com/{problem_id}",
        ease=2.5,
        interval_days=1,
        repetitions=1,
        due=due,
    )


def test_saved_card_round_trips(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    store.save(card("two-sum", date(2026, 1, 2)))

    assert store.get("leetcode", "two-sum") == card("two-sum", date(2026, 1, 2))
    assert store.get("leetcode", "missing") is None


def test_saving_again_replaces_the_card(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    store.save(card("two-sum", date(2026, 1, 2)))
    store.save(card("two-sum", date(2026, 1, 9)))

    saved = store.get("leetcode", "two-sum")
    assert saved is not None
    assert saved.due == date(2026, 1, 9)


def test_due_lists_overdue_first_and_skips_future(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    store.save(card("later", date(2026, 1, 10)))
    store.save(card("today", date(2026, 1, 5)))
    store.save(card("overdue", date(2026, 1, 1)))

    due = store.due(date(2026, 1, 5), limit=10)

    assert [c.problem_id for c in due] == ["overdue", "today"]


def test_opening_a_first_version_database_keeps_its_cards(tmp_path: Path) -> None:
    path = tmp_path / "coach.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            "CREATE TABLE review_cards (platform TEXT NOT NULL, problem_id TEXT NOT NULL, "
            "title TEXT NOT NULL, url TEXT NOT NULL, ease REAL NOT NULL, "
            "interval_days INTEGER NOT NULL, repetitions INTEGER NOT NULL, "
            "due TEXT NOT NULL, PRIMARY KEY (platform, problem_id));"
            "INSERT INTO review_cards VALUES "
            "('leetcode', 'two-sum', 'two-sum', 'https://example.com/two-sum', 2.5, 1, 1, "
            "'2026-01-02');"
        )

    store = ReviewStore(path)
    store.record_review(
        card("two-sum", date(2026, 1, 3)),
        ["array"],
        [Mistake(kind="off by one", note="loop bound")],
        date(2026, 1, 2),
    )

    assert store.get("leetcode", "two-sum") == card("two-sum", date(2026, 1, 3))
    assert [k.kind for k in store.mistake_kinds()] == ["off by one"]


def test_patterns_and_kinds_respect_since(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "coach.db")
    old, recent = date(2026, 1, 1), date(2026, 3, 1)
    store.record_review(card("a", old), ["dp"], [Mistake(kind="k", note="old")], old)
    store.record_review(card("b", recent), ["graph"], [Mistake(kind="k", note="new")], recent)

    patterns = store.patterns(since=recent - timedelta(days=1))

    assert [(k.kind, k.count) for k in patterns.kinds] == [("k", 1)]
    assert [(c.key, c.count) for c in patterns.by_tag] == [("graph", 1)]
    assert [(c.key, c.count) for c in patterns.by_month] == [("2026-03", 1)]
    assert [m.note for m in store.mistakes(tag="dp", limit=10)] == ["old"]
