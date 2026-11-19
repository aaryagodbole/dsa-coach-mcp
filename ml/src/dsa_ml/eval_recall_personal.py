"""Does the recall model get better once it has seen some of a user's own reviews?

For held-out users only. Each user's reviews are split in time: the first half is the
history dsa-coach would have, the second half is scored. Variants:

- the model as shipped (trained on other users);
- FSRS tuned on the user's first half;
- the model with a per-user correction (two numbers on the logit) fitted on the user's
  first half;
- a blend of the model and tuned FSRS, with blend weights learned on a *different*
  group of held-out users, so the scored users never shape the blend.

    uv run python -m dsa_ml.eval_recall_personal --users 30
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from .eval_platforms import _logit, recalibrate
from .eval_recall_fsrs import tuned_parameters
from .recall_features import load_revlog, user_events
from .train_recall import DEPLOYABLE, SEED
from .train_solve import scores

DATA = Path(__file__).resolve().parents[2] / "data"
ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"


def one_user(user_id: int) -> pd.DataFrame:
    revlog = load_revlog(user_id)
    half = len(revlog) // 2
    parameters = tuned_parameters(revlog.iloc[:half])
    events = user_events(user_id)
    events["fsrs_tuned_r"] = user_events(user_id, parameters)["fsrs_r"].to_numpy()
    events["later"] = events["row"] >= half
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=30)
    args = parser.parse_args()
    users = np.sort(
        pd.read_parquet(DATA / "recall_events.parquet", columns=["user"])["user"].unique()
    )
    rng = np.random.default_rng(SEED)
    held_out = sorted(rng.choice(users, size=len(users) // 4, replace=False).tolist())
    scored, blend_users = held_out[: args.users], held_out[args.users : 2 * args.users]
    with ProcessPoolExecutor(max_workers=6) as pool:
        frames = list(pool.map(one_user, scored + blend_users))
    events = pd.concat(frames, ignore_index=True)
    model = lgb.Booster(model_file=str(ARTIFACTS / "recall_small.txt"))
    events["model"] = model.predict(events[DEPLOYABLE])

    def blend_x(df: pd.DataFrame) -> np.ndarray:
        return np.column_stack(
            [_logit(df["model"].to_numpy()), _logit(df["fsrs_tuned_r"].to_numpy())]
        )

    train_blend = events[events["user"].isin(blend_users) & events["later"]]
    blender = LogisticRegression().fit(blend_x(train_blend), train_blend["y"])
    print("blend weights (model, tuned FSRS):", blender.coef_.round(3).tolist(), flush=True)

    rows = []
    for user in scored:
        mine = events[events["user"] == user]
        first, later = mine[~mine["later"]], mine[mine["later"]].copy()
        a, b = recalibrate(_logit(first["model"].to_numpy()), first["y"].to_numpy())
        later["corrected"] = 1 / (1 + np.exp(-(a * _logit(later["model"].to_numpy()) + b)))
        later["blend"] = blender.predict_proba(blend_x(later))[:, 1]
        rows.append(later)
    later = pd.concat(rows, ignore_index=True)
    y = later["y"].to_numpy()
    variants = {
        "FSRS, default": "fsrs_r",
        "FSRS, tuned on the user's first half": "fsrs_tuned_r",
        "model, as shipped": "model",
        "model + per-user correction": "corrected",
        "blend: model + tuned FSRS": "blend",
    }
    results = {name: scores(y, later[col].to_numpy()) for name, col in variants.items()}
    early = (later["n_reviews"] <= 2).to_numpy()
    for name, col in variants.items():
        results[name]["early reviews (<=2 before)"] = scores(y[early], later[col].to_numpy()[early])
        # Per user, then averaged: how it does for a typical person, not the busiest.
        per_user = [
            scores(g["y"].to_numpy(), g[col].to_numpy())["auc"]
            for _, g in later.groupby("user")
            if g["y"].nunique() == 2
        ]
        results[name]["mean AUC per user"] = round(float(np.mean(per_user)), 4)
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "recall_personal.json").write_text(json.dumps(results, indent=2))
    print(f"{len(scored)} scored users, {len(later)} later reviews")
    for name, r in results.items():
        main_scores = {k: v for k, v in r.items() if k in ("auc", "log_loss", "ece")}
        print(
            f"  {name:38s} {main_scores} early-auc {r['early reviews (<=2 before)']['auc']} "
            f"per-user-auc {r['mean AUC per user']}"
        )


if __name__ == "__main__":
    main()
