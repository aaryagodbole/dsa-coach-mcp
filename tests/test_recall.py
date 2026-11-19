from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fsrs import Rating

from dsa_coach_mcp import recall

DAY0 = datetime(2026, 1, 1, 9, tzinfo=UTC)


def test_the_shipped_trees_reproduce_lightgbm() -> None:
    # Rows and predictions written by LightGBM itself when the model was exported.
    reference = json.loads((Path(__file__).parent / "data" / "recall_reference.json").read_text())
    assert reference["features"] == recall._model()["features"]
    for row, expected in zip(reference["rows"], reference["expected"], strict=True):
        assert recall.predict(row) == pytest.approx(expected, abs=1e-6)


def test_features_describe_the_cards_history() -> None:
    reviews = [
        (Rating.Good, DAY0),
        (Rating.Again, DAY0 + timedelta(days=3)),
        (Rating.Hard, DAY0 + timedelta(days=5)),
    ]
    at = DAY0 + timedelta(days=12)

    row = recall.features(reviews, at, rate=0.9, seen=4)

    assert row is not None
    named = dict(zip(recall._model()["features"], row, strict=True))
    assert named["log_elapsed"] == pytest.approx(math.log1p(7))
    assert named["n_reviews"] == 3
    assert named["lapses"] == 1
    assert named["last_rating"] == 2
    assert named["log_prev_elapsed"] == pytest.approx(math.log1p(2))
    assert named["log_card_age"] == pytest.approx(math.log1p(12))
    assert named["mean_rating"] == pytest.approx(2.0)
    assert named["user_rate"] == 0.9
    assert named["log_user_seen"] == pytest.approx(math.log1p(4))
    assert 0 < named["fsrs_r"] < 1


def test_a_first_review_that_failed_is_not_a_lapse() -> None:
    row = recall.features([(Rating.Again, DAY0)], DAY0 + timedelta(days=2), 0.85, 0)

    assert row is not None
    assert dict(zip(recall._model()["features"], row, strict=True))["lapses"] == 0


def test_no_prediction_for_a_card_never_reviewed_or_reviewed_today() -> None:
    assert recall.features([], DAY0, 0.85, 0) is None
    assert recall.features([(Rating.Good, DAY0)], DAY0 + timedelta(hours=5), 0.85, 0) is None


def test_user_rate_counts_only_reviews_a_day_or_more_apart_before_now() -> None:
    cards = [
        [(Rating.Good, DAY0), (Rating.Again, DAY0 + timedelta(days=2))],
        # Same day: a learning step, not a counted review.
        [(Rating.Good, DAY0), (Rating.Good, DAY0 + timedelta(hours=2))],
        # After now: not yet happened.
        [(Rating.Good, DAY0), (Rating.Good, DAY0 + timedelta(days=30))],
    ]

    rate, seen = recall.user_rate(cards, DAY0 + timedelta(days=10))

    assert seen == 1
    assert rate == pytest.approx((0 + 10 * 0.85) / (1 + 10))


def test_recall_is_lower_the_longer_since_a_shaky_review() -> None:
    reviews = [(Rating.Good, DAY0), (Rating.Hard, DAY0 + timedelta(days=2))]
    cards = {("p", "a"): reviews}

    soon = recall.recall(cards, DAY0 + timedelta(days=4))[("p", "a")]
    late = recall.recall(cards, DAY0 + timedelta(days=90))[("p", "a")]

    assert 0 < late < soon < 1
