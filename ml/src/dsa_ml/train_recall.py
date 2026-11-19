"""Train and evaluate the recall model against FSRS.

Users are split, not reviews: models train on 75% of the users and are scored on the
other 25%, people they never saw, the way dsa-coach meets a new user. The baseline is
FSRS with default parameters, which is what dsa-coach schedules a new user with.

    uv run python -m dsa_ml.train_recall
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .train_solve import scores

DATA = Path(__file__).resolve().parents[2] / "data"
ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"
SEED = 7
HISTORY = [
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
]
FSRS = ["fsrs_r", "fsrs_log_stability", "fsrs_difficulty"]
# Answer time is in Anki's logs but not in dsa-coach's, so the model dsa-coach can use
# leaves it out.
DEPLOYABLE = [c for c in HISTORY if "duration" not in c] + FSRS
PARAMS = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 500,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "seed": SEED,
    "verbose": -1,
}


def main() -> None:
    events = pd.read_parquet(DATA / "recall_events.parquet")
    users = np.sort(events["user"].unique())
    rng = np.random.default_rng(SEED)
    test_users = set(rng.choice(users, size=len(users) // 4, replace=False).tolist())
    is_test = events["user"].isin(test_users).to_numpy()
    train, test = events[~is_test], events[is_test]
    sample = train.sample(min(len(train), 4_000_000), random_state=SEED)
    print(
        f"train {len(train)} reviews / {len(users) - len(test_users)} users; "
        f"test {len(test)} reviews / {len(test_users)} users",
        flush=True,
    )

    history = lgb.train(PARAMS, lgb.Dataset(sample[HISTORY], sample["y"]), 400)
    hybrid = lgb.train(PARAMS, lgb.Dataset(sample[HISTORY + FSRS], sample["y"]), 400)
    deployable = lgb.train(PARAMS, lgb.Dataset(sample[DEPLOYABLE], sample["y"]), 400)

    y = test["y"].to_numpy()
    predictions = {
        "FSRS, default parameters (dsa-coach today)": test["fsrs_r"].to_numpy(),
        "LightGBM on review history": history.predict(test[HISTORY]),
        "LightGBM on history + FSRS state (hybrid)": hybrid.predict(test[HISTORY + FSRS]),
        "hybrid without answer time (what dsa-coach records)": deployable.predict(test[DEPLOYABLE]),
    }
    results = {name: scores(y, p) for name, p in predictions.items()}
    # Where the models disagree most: cards seen only once or twice before.
    early = (test["n_reviews"] <= 2).to_numpy()
    for name, p in predictions.items():
        results[name]["early reviews (<=2 before)"] = scores(y[early], p[early])

    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "recall_results.json").write_text(json.dumps(results, indent=2))
    hybrid.save_model(str(ARTIFACTS / "recall_lightgbm.txt"))
    deployable.save_model(str(ARTIFACTS / "recall_lightgbm_deployable.txt"))
    importance = dict(
        zip(
            HISTORY + FSRS,
            hybrid.feature_importance("gain").round().astype(int).tolist(),
            strict=True,
        )
    )
    (ARTIFACTS / "recall_importance.json").write_text(json.dumps(importance, indent=2))

    table = pd.DataFrame(
        {
            k: {m: v for m, v in r.items() if m != "early reviews (<=2 before)"}
            for k, r in results.items()
        }
    ).T
    print(table.to_string())
    print("\nearly reviews:")
    print(pd.DataFrame({k: r["early reviews (<=2 before)"] for k, r in results.items()}).T)
    print(f"\ntest recall rate {y.mean():.3f}; early share {early.mean():.2f}")


if __name__ == "__main__":
    main()
