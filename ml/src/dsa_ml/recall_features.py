"""Features for predicting recall at each review, from Anki review logs.

For every review at least a day after the card's previous one, the target is whether
the user remembered (any rating but "again"). Features describe only the card's and
the user's history before that review, plus what FSRS with default parameters, the
scheduler dsa-coach uses for a new user, predicts at that moment.

    uv run python -m dsa_ml.recall_features --users 400
"""

from __future__ import annotations

import argparse
import math
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from fsrs import Card, Rating, Scheduler

DATA = Path(__file__).resolve().parents[2] / "data"
REVLOGS = DATA / "raw" / "anki" / "revlogs"
START = datetime(2000, 1, 1, tzinfo=UTC)
# A few users have hundreds of thousands of reviews; cap each so no one dominates.
MAX_REVIEWS_PER_USER = 60_000
PRIOR = 10.0


def user_events(user_id: int) -> pd.DataFrame:
    df = pd.read_parquet(REVLOGS / f"user_id={user_id}" / "data.parquet")
    df = df.head(MAX_REVIEWS_PER_USER)
    scheduler = Scheduler(learning_steps=(), relearning_steps=(), enable_fuzzing=False)
    cards: dict[int, Card] = {}
    history: dict[int, list[float]] = {}
    rows = []
    user_seen = user_hits = 0
    base = 0.85  # prior for a user's recall rate before their first counted review
    for card_id, day, rating, duration, elapsed in zip(
        df["card_id"].to_numpy(),
        df["day_offset"].to_numpy(),
        df["rating"].to_numpy(),
        df["duration"].to_numpy(),
        df["elapsed_days"].to_numpy(),
        strict=True,
    ):
        at = START + timedelta(days=int(day))
        card = cards.get(card_id)
        h = history.get(card_id)
        if card is not None and h is not None and elapsed >= 1:
            # h: n reviews, lapses, last rating, previous elapsed, first day, sum of
            # ratings, sum of log durations, last duration
            n, lapses, last_rating, prev_elapsed, first_day, rating_sum, logdur_sum, last_dur = h
            r = scheduler.get_card_retrievability(card, at)
            y = int(rating > 1)
            rows.append(
                (
                    user_id,
                    y,
                    math.log1p(elapsed),
                    n,
                    lapses,
                    last_rating,
                    math.log1p(prev_elapsed),
                    math.log1p(day - first_day),
                    rating_sum / n,
                    logdur_sum / n,
                    math.log1p(last_dur),
                    (user_hits + PRIOR * base) / (user_seen + PRIOR),
                    math.log1p(user_seen),
                    r,
                    math.log(card.stability or 1e-3),
                    card.difficulty or 5.0,
                )
            )
            user_seen += 1
            user_hits += y
        card = card or Card()
        cards[card_id], _ = scheduler.review_card(card, Rating(int(rating)), review_datetime=at)
        log_dur = math.log1p(duration)
        if h is None:
            history[card_id] = [1, 0, rating, 0, day, rating, log_dur, duration]
        else:
            h[0] += 1
            h[1] += int(rating == 1)
            h[2] = rating
            h[3] = max(int(elapsed), 0)
            h[5] += rating
            h[6] += log_dur
            h[7] = duration
    return pd.DataFrame(rows, columns=COLUMNS)


COLUMNS = [
    "user",
    "y",
    "log_elapsed",
    "n_reviews",
    "lapses",
    "last_rating",
    "log_prev_elapsed",
    "log_card_age",
    "mean_rating",
    "mean_log_duration",
    "log_last_duration",
    "user_rate",
    "log_user_seen",
    "fsrs_r",
    "fsrs_log_stability",
    "fsrs_difficulty",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=400)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    available = sorted(int(p.name.split("=")[1]) for p in REVLOGS.glob("user_id=*"))
    rng = np.random.default_rng(args.seed)
    users = sorted(rng.choice(available, size=min(args.users, len(available)), replace=False))
    with ProcessPoolExecutor() as pool:
        frames = list(pool.map(user_events, users, chunksize=4))
    events = pd.concat(frames, ignore_index=True)
    events.to_parquet(DATA / "recall_events.parquet", index=False)
    print(f"{len(events)} review events from {len(users)} users, recall {events['y'].mean():.3f}")


if __name__ == "__main__":
    main()
