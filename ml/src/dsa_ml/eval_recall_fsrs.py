"""Score the recall model against FSRS tuned to each user, the fair baseline.

For each held-out user, FSRS's parameters are fitted on the first half of their reviews
(as dsa-coach's personalize_schedule would), then default FSRS, tuned FSRS and the
recall model (trained on other users) are scored on the second half, which none of them
trained on.

    uv run python -m dsa_ml.eval_recall_fsrs --users 30
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from fsrs import Optimizer, Rating, ReviewLog

from .recall_features import START, load_revlog, user_events
from .train_recall import DEPLOYABLE, SEED
from .train_solve import scores

DATA = Path(__file__).resolve().parents[2] / "data"
ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"


def tuned_parameters(revlog: pd.DataFrame) -> tuple[float, ...]:
    logs = [
        ReviewLog(
            card_id=int(c),
            rating=Rating(int(r)),
            review_datetime=START + timedelta(days=int(d)),
            review_duration=int(ms),
        )
        for c, r, d, ms in zip(
            revlog["card_id"],
            revlog["rating"],
            revlog["day_offset"],
            revlog["duration"],
            strict=True,
        )
    ]
    return tuple(Optimizer(logs).compute_optimal_parameters())


def one_user(user_id: int) -> pd.DataFrame:
    revlog = load_revlog(user_id)
    half = len(revlog) // 2
    parameters = tuned_parameters(revlog.iloc[:half])
    default = user_events(user_id)
    tuned = user_events(user_id, parameters)
    later = default["row"] >= half
    out = default[later].copy()
    out["fsrs_tuned_r"] = tuned.loc[later.to_numpy(), "fsrs_r"].to_numpy()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=30)
    args = parser.parse_args()
    # The same held-out users as train_recall.
    events_users = np.sort(
        pd.read_parquet(DATA / "recall_events.parquet", columns=["user"])["user"].unique()
    )
    rng = np.random.default_rng(SEED)
    held_out = sorted(rng.choice(events_users, size=len(events_users) // 4, replace=False).tolist())
    users = held_out[: args.users]
    with ProcessPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(one_user, users))
    events = pd.concat(frames, ignore_index=True)
    model = lgb.Booster(model_file=str(ARTIFACTS / "recall_lightgbm_deployable.txt"))
    y = events["y"].to_numpy()
    predictions = {
        "FSRS, default parameters": events["fsrs_r"].to_numpy(),
        "FSRS, tuned on the user's first half": events["fsrs_tuned_r"].to_numpy(),
        "recall model (trained on other users)": model.predict(events[DEPLOYABLE]),
    }
    results = {name: scores(y, p) for name, p in predictions.items()}
    early = (events["n_reviews"] <= 2).to_numpy()
    for name, p in predictions.items():
        results[name]["early reviews (<=2 before)"] = scores(y[early], p[early])
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "recall_vs_tuned_fsrs.json").write_text(json.dumps(results, indent=2))
    print(f"{len(users)} held-out users, {len(events)} later reviews scored")
    for name, r in results.items():
        print(
            f"  {name:40s} { ({k: v for k, v in r.items() if k != 'early reviews (<=2 before)'}) }  early {r['early reviews (<=2 before)']}"
        )


if __name__ == "__main__":
    main()
