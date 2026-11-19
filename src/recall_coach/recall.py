"""The chance a user still remembers a problem, from the recall model in trained/.

The model is gradient-boosted trees trained on 7M reviews from 300 Anki users (see
ml/README.md). On users it never saw it ranks recall better than FSRS tuned to each
user's own history. Its trees ship as plain arrays, so predicting needs no ML library.

Each feature is computed exactly as in training: from the card's earlier reviews, the
user's running recall rate, and the state FSRS with default parameters holds at that
moment. The model was trained only on reviews at least a day after the previous one;
for a card reviewed today it gives no prediction and FSRS's is used instead.
"""

from __future__ import annotations

import gzip
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from functools import cache
from importlib.resources import files
from itertools import pairwise
from typing import Any

from fsrs import Card, Rating

from . import scheduling

# The user's recall rate before they have any counted reviews, and how many reviews'
# worth of weight that guess carries; both as in training.
USER_BASE = 0.85
USER_PRIOR = 10.0

Review = tuple[Rating, datetime]


@cache
def _model() -> dict[str, Any]:
    with gzip.open(files("recall_coach.trained").joinpath("recall.json.gz").open("rb"), "rt") as f:
        model: dict[str, Any] = json.load(f)
    return model


@cache
def _default_scheduler() -> scheduling.Scheduler:
    # The model's FSRS features come from default parameters, whatever the user's own.
    return scheduling.make_scheduler(None, fuzz=False)


def _days(later: datetime, earlier: datetime) -> int:
    return (later.date() - earlier.date()).days


def user_rate(cards: Iterable[Sequence[Review]], at: datetime) -> tuple[float, int]:
    """The user's smoothed recall rate over reviews a day or more after the previous
    one, before ``at``, and how many such reviews there were."""

    seen = hits = 0
    for reviews in cards:
        for (_, before), (rating, when) in pairwise(reviews):
            if when < at and _days(when, before) >= 1:
                seen += 1
                hits += rating != Rating.Again
    return (hits + USER_PRIOR * USER_BASE) / (seen + USER_PRIOR), seen


def features(reviews: Sequence[Review], at: datetime, rate: float, seen: int) -> list[float] | None:
    """The model's inputs for recalling this card at ``at``, or None where the model
    does not apply (never reviewed, or reviewed earlier the same day)."""

    if not reviews or _days(at, reviews[-1][1]) < 1:
        return None
    fsrs = _default_scheduler()
    card = Card()
    for rating, when in reviews:
        card, _ = fsrs.review_card(card, rating, review_datetime=when)
    ratings = [int(r) for r, _ in reviews]
    previous_gap = _days(reviews[-1][1], reviews[-2][1]) if len(reviews) > 1 else 0
    values = {
        "log_elapsed": math.log1p(_days(at, reviews[-1][1])),
        "n_reviews": len(reviews),
        # As in training, the first review is a first attempt, not a lapse.
        "lapses": sum(r == int(Rating.Again) for r in ratings[1:]),
        "last_rating": ratings[-1],
        "log_prev_elapsed": math.log1p(max(previous_gap, 0)),
        "log_card_age": math.log1p(_days(at, reviews[0][1])),
        "mean_rating": sum(ratings) / len(ratings),
        "user_rate": rate,
        "log_user_seen": math.log1p(seen),
        "fsrs_r": fsrs.get_card_retrievability(card, at),
        "fsrs_log_stability": math.log(card.stability or 1e-3),
        "fsrs_difficulty": card.difficulty or 5.0,
    }
    return [float(values[name]) for name in _model()["features"]]


def predict(row: Sequence[float]) -> float:
    total = 0.0
    for nodes in _model()["trees"]:
        i = 0
        while len(nodes[i]) == 4:
            feature, threshold, left, right = nodes[i]
            i = left if row[feature] <= threshold else right
        total += nodes[i][0]
    return 1 / (1 + math.exp(-total))


def recall(
    cards: Mapping[tuple[str, str], Sequence[Review]],
    at: datetime,
    only: Iterable[tuple[str, str]] | None = None,
) -> dict[tuple[str, str], float]:
    """The model's recall chance, by (platform, id), for the cards in ``only`` (all if
    None) that it applies to. ``cards`` is every card, for the user's recall rate."""

    rate, seen = user_rate(cards.values(), at)
    out = {}
    wanted = cards.keys() if only is None else only
    for key in wanted:
        reviews = cards.get(key, ())
        row = features(reviews, at, rate, seen)
        if row is not None:
            out[key] = predict(row)
    return out
