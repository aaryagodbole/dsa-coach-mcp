"""SuperMemo-2 spaced repetition.

Constants are the algorithm's own, as published by P. A. Wozniak (1990):
https://super-memory.com/english/ol/sm2.htm
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

INITIAL_EASE = 2.5
MIN_EASE = 1.3
MIN_QUALITY = 0
MAX_QUALITY = 5
PASSING_QUALITY = 3


@dataclass(frozen=True)
class Schedule:
    ease: float
    interval_days: int
    repetitions: int
    due: date


def review(previous: Schedule | None, quality: int, today: date) -> Schedule:
    """Next schedule after recalling a problem with ``quality`` (0 = blackout, 5 = perfect)."""

    if not MIN_QUALITY <= quality <= MAX_QUALITY:
        raise ValueError(f"quality must be between {MIN_QUALITY} and {MAX_QUALITY}")

    ease = previous.ease if previous else INITIAL_EASE
    repetitions = previous.repetitions if previous else 0
    interval = previous.interval_days if previous else 0

    if quality < PASSING_QUALITY:
        repetitions, interval = 0, 1
    else:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 6
        else:
            interval = round(interval * ease)
        repetitions += 1

    miss = MAX_QUALITY - quality
    ease = max(MIN_EASE, ease + 0.1 - miss * (0.08 + miss * 0.02))
    return Schedule(ease, interval, repetitions, today + timedelta(days=interval))
