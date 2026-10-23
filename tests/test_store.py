from __future__ import annotations

from datetime import date
from pathlib import Path

from dsa_coach_mcp.models import ReviewCard
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
