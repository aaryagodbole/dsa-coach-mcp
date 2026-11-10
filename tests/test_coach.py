from __future__ import annotations

from datetime import UTC, date, datetime

from dsa_coach_mcp.coach import next_steps
from dsa_coach_mcp.models import (
    AccountStats,
    Insights,
    MistakeRecovery,
    OverconfidentReview,
    ReviewCard,
    TagCount,
    TopicForecast,
)

AT = datetime(2026, 1, 1, tzinfo=UTC)


def card(problem_id: str, recall: float | None) -> ReviewCard:
    return ReviewCard(
        platform="leetcode",
        problem_id=problem_id,
        title=problem_id.title(),
        url=f"https://example.com/{problem_id}",
        due=AT,
        retrievability=recall,
    )


def insights(**fields: object) -> Insights:
    base: dict[str, object] = {
        "horizon_days": 14,
        "forecast": [],
        "recovery": [],
        "overconfidence": [],
        "calibration": [],
    }
    return Insights.model_validate(base | fields)


def recovery(kind: str, times: int, clean: int, day: int = 1) -> MistakeRecovery:
    return MistakeRecovery(
        kind=kind, times=times, last_seen=date(2026, 1, day), clean_reviews_since=clean
    )


def test_nothing_to_go_on_suggests_nothing() -> None:
    assert next_steps([], insights(), []) == []


def test_revises_the_problem_most_likely_forgotten() -> None:
    (step,) = next_steps([card("new", None), card("a", 0.8), card("b", 0.54)], insights(), [])

    assert (step.kind, step.title, step.url) == ("revise", "Revise B", "https://example.com/b")
    assert step.detail == "54% chance you still remember it."


def test_a_new_card_is_revised_when_nothing_due_has_been_reviewed() -> None:
    (step,) = next_steps([card("fresh", None)], insights(), [])

    assert (step.title, step.detail) == ("Revise Fresh", "Due for its first revision.")


def test_picks_the_most_frequent_mistake_with_no_clean_review_since() -> None:
    data = insights(
        recovery=[
            recovery("off by one", 5, clean=2),
            recovery("missed cycle", 3, clean=0, day=2),
            recovery("edge case", 3, clean=0, day=1),
            recovery("overflow", 1, clean=0),
        ]
    )

    (step,) = next_steps([], data, [])

    assert (step.kind, step.title) == ("mistake", "Watch for: missed cycle")
    assert step.detail.startswith("Happened 3 times")


def test_a_single_mistake_reads_once() -> None:
    (step,) = next_steps([], insights(recovery=[recovery("overflow", 1, clean=0)]), [])

    assert step.detail.startswith("Happened once")


def test_topic_prefers_tags_tried_and_never_solved_on_a_linked_account() -> None:
    accounts = [
        AccountStats(platform="codeforces", handle="a", struggling=[TagCount(tag="dp", count=7)]),
        AccountStats(platform="broken", handle="a", error="down"),
    ]
    data = insights(
        forecast=[TopicForecast(tag="graph", problems=2, recall_now=0.6, recall_later=0.4)]
    )

    (step,) = next_steps([], data, accounts)

    assert (step.kind, step.title) == ("topic", "Practise dp")
    assert step.detail == "7 dp problems tried and never solved on codeforces."


def test_topic_falls_back_to_the_tag_forgotten_fastest() -> None:
    data = insights(
        forecast=[
            TopicForecast(tag="graph", problems=2, recall_now=0.7, recall_later=0.58),
            TopicForecast(tag="dp", problems=1, recall_now=0.8, recall_later=0.75),
        ]
    )

    (step,) = next_steps([], data, [])

    assert (step.title, step.detail) == (
        "Practise graph",
        "Recall falls to 58% in 14 days without revising.",
    )


def test_no_topic_step_while_every_tag_stays_remembered() -> None:
    data = insights(
        forecast=[TopicForecast(tag="dp", problems=1, recall_now=0.9, recall_later=0.8)]
    )

    assert next_steps([], data, []) == []


def test_rechecks_the_latest_overconfident_review() -> None:
    def review(problem_id: str, day: int) -> OverconfidentReview:
        return OverconfidentReview(
            platform="leetcode",
            problem_id=problem_id,
            title=problem_id.title(),
            url=f"https://example.com/{problem_id}",
            rated_easy_at=AT,
            forgot_at=datetime(2026, 1, day, tzinfo=UTC),
        )

    (step,) = next_steps([], insights(overconfidence=[review("old", 2), review("new", 5)]), [])

    assert (step.kind, step.title) == ("recheck", "Re-check New")


def test_steps_come_in_a_fixed_order() -> None:
    data = insights(
        recovery=[recovery("k", 2, clean=0)],
        forecast=[TopicForecast(tag="dp", problems=1, recall_now=0.6, recall_later=0.5)],
        overconfidence=[
            OverconfidentReview(
                platform="leetcode",
                problem_id="x",
                title="X",
                url="https://example.com/x",
                rated_easy_at=AT,
                forgot_at=AT,
            )
        ],
    )

    steps = next_steps([card("a", 0.5)], data, [])

    assert [s.kind for s in steps] == ["revise", "mistake", "topic", "recheck"]
