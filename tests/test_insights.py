from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fsrs import Card, Rating

from dsa_coach_mcp.insights import calibration, forecast, overconfidence, recovery
from dsa_coach_mcp.scheduling import make_scheduler
from dsa_coach_mcp.store import CardHistory

AT = datetime(2026, 3, 1, 9, tzinfo=UTC)
FSRS = make_scheduler(None, fuzz=False)


def history(
    problem_id: str,
    reviews: list[tuple[Rating, int]],
    tags: list[str] | None = None,
    mistakes: list[tuple[str, int]] | None = None,
) -> CardHistory:
    """A card replayed through FSRS; review and mistake times are days before AT."""

    card = Card()
    timed = [(rating, AT - timedelta(days=days)) for rating, days in reviews]
    for rating, at in timed:
        card, _ = FSRS.review_card(card, rating, review_datetime=at)
    return CardHistory(
        platform="leetcode",
        problem_id=problem_id,
        title=problem_id,
        url=f"https://example.com/{problem_id}",
        tags=tags or [],
        card=card,
        reviews=timed,
        mistakes=[(kind, (AT - timedelta(days=days)).date()) for kind, days in mistakes or []],
    )


def test_forecast_drops_faster_for_weakly_remembered_tags() -> None:
    shaky = history("shaky", [(Rating.Hard, 3)], tags=["graph"])
    solid = history("solid", [(Rating.Easy, 40), (Rating.Easy, 3)], tags=["array"])
    unreviewed = CardHistory("leetcode", "new", "new", "u", ["graph"], Card(), [], [])

    graph, array = forecast([solid, shaky, unreviewed], FSRS, AT, 14)

    assert (graph.tag, graph.problems) == ("graph", 1)
    assert array.tag == "array"
    for topic in (graph, array):
        assert 0 < topic.recall_later < topic.recall_now <= 1
    assert graph.recall_now - graph.recall_later > array.recall_now - array.recall_later


def test_forecast_counts_a_problem_once_per_tag() -> None:
    (topic,) = forecast([history("a", [(Rating.Good, 1)], tags=["dp", "dp"])], FSRS, AT, 14)
    assert topic.problems == 1


def test_recovery_counts_only_reviews_on_later_days() -> None:
    fixed = history(
        "fixed",
        [(Rating.Again, 10), (Rating.Good, 6), (Rating.Good, 2)],
        mistakes=[("off by one", 10)],
    )
    # Logged again on the same day as its latest review: nothing after it yet.
    repeating = history(
        "repeating",
        [(Rating.Hard, 9), (Rating.Hard, 1)],
        mistakes=[("missed edge case", 9), ("missed edge case", 1)],
    )

    still, recovered = recovery([fixed, repeating])

    assert (still.kind, still.times, still.clean_reviews_since) == ("missed edge case", 2, 0)
    assert still.last_seen == (AT - timedelta(days=1)).date()
    assert (recovered.kind, recovered.times, recovered.clean_reviews_since) == ("off by one", 1, 2)


def test_overconfidence_finds_easy_followed_by_a_fail() -> None:
    fooled = history("fooled", [(Rating.Easy, 20), (Rating.Again, 5), (Rating.Good, 1)])
    fine = history("fine", [(Rating.Easy, 20), (Rating.Hard, 5)])
    late = history("late", [(Rating.Easy, 9), (Rating.Again, 2)])

    found = overconfidence([fooled, fine, late])

    assert [r.problem_id for r in found] == ["late", "fooled"]
    assert found[1].rated_easy_at == AT - timedelta(days=20)
    assert found[1].forgot_at == AT - timedelta(days=5)


def test_calibration_scores_every_review_after_the_first() -> None:
    cards = [
        history("a", [(Rating.Good, 30), (Rating.Good, 25), (Rating.Again, 1)]),
        history("b", [(Rating.Good, 10)]),
    ]

    bins = calibration(cards, FSRS)

    assert sum(b.reviews for b in bins) == 2
    assert sum(b.recalled * b.reviews for b in bins) == 1
    for b in bins:
        assert b.low <= b.predicted < b.high or b.predicted == b.high == 1.0


def test_no_history_gives_empty_insights() -> None:
    assert forecast([], FSRS, AT, 14) == []
    assert recovery([]) == []
    assert overconfidence([]) == []
    assert calibration([], FSRS) == []


def test_mistake_dates_compare_by_day() -> None:
    (r,) = recovery([history("x", [(Rating.Good, 0)], mistakes=[("k", 0)])])
    assert r.last_seen == date(2026, 3, 1)
    assert r.clean_reviews_since == 0
