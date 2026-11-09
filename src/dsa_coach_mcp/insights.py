"""What the review history says about the user's memory, for the dashboard.

Every function reads the same card histories and returns plain numbers; reading them
is left to the user and the model."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from itertools import pairwise

from fsrs import Card, Rating, Scheduler

from .models import (
    CalibrationBin,
    Insights,
    MistakeRecovery,
    OverconfidentReview,
    TopicForecast,
)
from .store import CardHistory

# Wider at the bottom, where few reviews land once the schedule settles.
CALIBRATION_EDGES = (0.0, 0.5, 0.7, 0.8, 0.9, 1.0)


def insights(
    histories: Sequence[CardHistory], scheduler: Scheduler, at: datetime, horizon_days: int
) -> Insights:
    return Insights(
        horizon_days=horizon_days,
        forecast=forecast(histories, scheduler, at, horizon_days),
        recovery=recovery(histories),
        overconfidence=overconfidence(histories),
        calibration=calibration(histories, scheduler),
    )


def forecast(
    histories: Sequence[CardHistory], scheduler: Scheduler, at: datetime, horizon_days: int
) -> list[TopicForecast]:
    """Mean recall per tag now and after the horizon, steepest drop first."""

    later = at + timedelta(days=horizon_days)
    now_by_tag: dict[str, list[float]] = defaultdict(list)
    later_by_tag: dict[str, list[float]] = defaultdict(list)
    for history in histories:
        if history.card.last_review is None:
            continue
        for tag in set(history.tags):
            now_by_tag[tag].append(scheduler.get_card_retrievability(history.card, at))
            later_by_tag[tag].append(scheduler.get_card_retrievability(history.card, later))
    topics = [
        TopicForecast(
            tag=tag,
            problems=len(values),
            recall_now=sum(values) / len(values),
            recall_later=sum(later_by_tag[tag]) / len(values),
        )
        for tag, values in now_by_tag.items()
    ]
    return sorted(topics, key=lambda t: (t.recall_later - t.recall_now, t.tag))


def recovery(histories: Sequence[CardHistory]) -> list[MistakeRecovery]:
    """Per mistake label: how often it happened, and how many reviews of the problems it
    happened on came after its last occurrence. A review on the day it was logged is the
    one that logged it, so only later days count."""

    times: dict[str, int] = defaultdict(int)
    last_seen: dict[str, date] = {}
    cards_by_kind: dict[str, dict[tuple[str, str], CardHistory]] = defaultdict(dict)
    for history in histories:
        for kind, logged_on in history.mistakes:
            times[kind] += 1
            last_seen[kind] = max(last_seen.get(kind, logged_on), logged_on)
            cards_by_kind[kind][history.platform, history.problem_id] = history
    result = [
        MistakeRecovery(
            kind=kind,
            times=times[kind],
            last_seen=last_seen[kind],
            clean_reviews_since=sum(
                1
                for history in cards_by_kind[kind].values()
                for _, reviewed_at in history.reviews
                if reviewed_at.date() > last_seen[kind]
            ),
        )
        for kind in times
    ]
    return sorted(result, key=lambda r: (r.clean_reviews_since, -r.times, r.kind))


def overconfidence(histories: Sequence[CardHistory]) -> list[OverconfidentReview]:
    """Problems rated easy whose very next review was a fail, latest first."""

    found = [
        OverconfidentReview(
            platform=history.platform,
            problem_id=history.problem_id,
            title=history.title,
            url=history.url,
            rated_easy_at=easy_at,
            forgot_at=forgot_at,
        )
        for history in histories
        for (first, easy_at), (second, forgot_at) in pairwise(history.reviews)
        if first == Rating.Easy and second == Rating.Again
    ]
    return sorted(found, key=lambda r: r.forgot_at, reverse=True)


def calibration(histories: Sequence[CardHistory], scheduler: Scheduler) -> list[CalibrationBin]:
    """How often the user recalled a problem against how likely FSRS said it was.

    Each card's reviews are replayed from scratch with the current parameters, and every
    review after the first is scored by the recall predicted just before it; a review is
    recalled unless it was rated again. Bins with no reviews are left out."""

    pairs: list[tuple[float, bool]] = []
    for history in histories:
        card = Card()
        for index, (rating, reviewed_at) in enumerate(history.reviews):
            if index:
                pairs.append(
                    (scheduler.get_card_retrievability(card, reviewed_at), rating != Rating.Again)
                )
            card, _ = scheduler.review_card(card, rating, review_datetime=reviewed_at)
    bins = []
    for low, high in pairwise(CALIBRATION_EDGES):
        inside = [(p, ok) for p, ok in pairs if low <= p < high or (high == 1.0 and p == 1.0)]
        if inside:
            bins.append(
                CalibrationBin(
                    low=low,
                    high=high,
                    reviews=len(inside),
                    predicted=sum(p for p, _ in inside) / len(inside),
                    recalled=sum(ok for _, ok in inside) / len(inside),
                )
            )
    return bins
