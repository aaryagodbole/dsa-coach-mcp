"""FSRS scheduling, via py-fsrs (https://github.com/open-spaced-repetition/py-fsrs).

FSRS predicts how likely the user is to recall each problem and schedules the next
review for when that chance drops to the desired retention. Its parameters can be
fitted to the user's own review history (see ``optimize``)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from fsrs import Card, Rating, ReviewLog, Scheduler
from fsrs.scheduler import DEFAULT_PARAMETERS

__all__ = [
    "Card",
    "ReviewRating",
    "Scheduler",
    "is_default",
    "make_scheduler",
    "optimize",
    "review",
    "to_rating",
]

# The ratings FSRS defines, named as the library names them.
ReviewRating = StrEnum("ReviewRating", [rating.name.lower() for rating in Rating])  # type: ignore[misc]


def make_scheduler(parameters: Sequence[float] | None, *, fuzz: bool = True) -> Scheduler:
    """A scheduler measured in days.

    A review here means re-solving a problem, so FSRS's minute-scale learning steps
    would only ask the user to repeat it the same afternoon; with none, the first
    review already schedules days ahead."""

    if parameters is None:
        return Scheduler(learning_steps=(), relearning_steps=(), enable_fuzzing=fuzz)
    return Scheduler(
        parameters=tuple(parameters), learning_steps=(), relearning_steps=(), enable_fuzzing=fuzz
    )


def to_rating(rating: ReviewRating) -> Rating:
    return Rating[str(rating.value).capitalize()]


def review(
    scheduler: Scheduler, card: Card, rating: ReviewRating, at: datetime
) -> tuple[Card, ReviewLog]:
    return scheduler.review_card(card, to_rating(rating), review_datetime=at)


def optimize(logs: Sequence[ReviewLog]) -> list[float]:
    """FSRS parameters fitted to these reviews. Needs the ``optimizer`` extra."""

    try:
        from fsrs import Optimizer
    except ImportError as exc:  # torch and friends are optional
        raise RuntimeError(
            "Personalising the schedule needs the optimizer extra: "
            "pip install 'dsa-coach-mcp[optimizer]'"
        ) from exc
    return list(Optimizer(list(logs)).compute_optimal_parameters())


def is_default(parameters: Sequence[float]) -> bool:
    """Whether these are FSRS's stock parameters, which the optimizer also returns
    when the history is too short to fit."""

    return tuple(parameters) == tuple(DEFAULT_PARAMETERS)
