from __future__ import annotations

from datetime import date, timedelta

import pytest

from dsa_coach_mcp import srs

TODAY = date(2026, 1, 1)


def test_first_two_passes_follow_the_fixed_sm2_intervals() -> None:
    first = srs.review(None, 5, TODAY)
    second = srs.review(first, 5, TODAY)

    assert (first.interval_days, first.repetitions) == (1, 1)
    assert (second.interval_days, second.repetitions) == (6, 2)
    assert second.due == TODAY + timedelta(days=6)


def test_later_passes_grow_by_ease() -> None:
    schedule = srs.review(srs.review(None, 5, TODAY), 5, TODAY)
    third = srs.review(schedule, 5, TODAY)

    assert third.interval_days == round(6 * schedule.ease)


def test_a_failed_recall_restarts_the_schedule() -> None:
    learned = srs.review(srs.review(None, 5, TODAY), 5, TODAY)
    failed = srs.review(learned, 1, TODAY)

    assert (failed.interval_days, failed.repetitions) == (1, 0)
    assert failed.ease < learned.ease


def test_ease_never_drops_below_the_floor() -> None:
    schedule = None
    for _ in range(20):
        schedule = srs.review(schedule, 0, TODAY)

    assert schedule is not None
    assert schedule.ease == srs.MIN_EASE


@pytest.mark.parametrize("quality", [-1, 6])
def test_quality_out_of_range_is_rejected(quality: int) -> None:
    with pytest.raises(ValueError, match="quality"):
        srs.review(None, quality, TODAY)
