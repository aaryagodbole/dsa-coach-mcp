"""Tune topic Elo's settings without peeking at the judge being evaluated.

Every setting in a small grid is run on every judge once. For each judge held out, the
setting with the best mean log-loss on the *other* judges is chosen and that judge is
scored with it, as trained and after two-stage recalibration (eval_platforms). The
setting dsa-coach ships is the one best across all judges.

    uv run python -m dsa_ml.tune_elo
"""

from __future__ import annotations

import itertools
import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

from . import elo
from .eval_platforms import CALIBRATION_SHARE, _logit, recalibrate
from .features import codeforces_topics, published_difficulty
from .train_solve import scores

DATA = Path(__file__).resolve().parents[2] / "data"
ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"
GRID = {
    "prior_scale": (0.15, 0.3, 0.5),
    "k_user": (0.2, 0.4),
    "k_topic": (0.1, 0.3),
}


def judges() -> dict[str, dict]:
    attempts = pd.read_parquet(DATA / "attempts.parquet")
    published = published_difficulty()
    topics_of = {"codeforces": codeforces_topics()}
    out = {}
    for source, df in attempts.groupby("source"):
        source = str(source)
        df = df.sort_values("at", kind="stable")
        problem_cat = df["problem"].astype("category")
        names = list(problem_cat.cat.categories)
        out[source] = {
            "users": df["user"].astype("category").cat.codes.to_numpy(),
            "problems": problem_cat.cat.codes.to_numpy(),
            "topics": [topics_of.get(source, {}).get(p, []) for p in names],
            "y": (df["solved"] & (df["tries"] == 1)).to_numpy(dtype=float),
            "rating": np.array(
                [published.get(source, {}).get(p, np.nan) for p in names], dtype=float
            ),
        }
    return out


def main() -> None:
    data = judges()
    settings = [
        replace(elo.Settings(), **dict(zip(GRID, values, strict=True)))
        for values in itertools.product(*GRID.values())
    ]
    # predictions[i][judge]: the setting's predictions on that judge, in time order.
    predictions: list[dict[str, np.ndarray]] = []
    losses: list[dict[str, float]] = []
    for i, s in enumerate(settings):
        preds, loss = {}, {}
        for name, d in data.items():
            p = elo.run(d["users"], d["problems"], d["topics"], d["y"], d["rating"], s)["p"]
            preds[name] = p
            loss[name] = scores(d["y"], p)["log_loss"]
        predictions.append(preds)
        losses.append(loss)
        print(i, {k: v for k, v in asdict(s).items() if k in GRID}, loss, flush=True)

    results = {}
    for held_out, d in data.items():
        others = [j for j in data if j != held_out]
        best = min(range(len(settings)), key=lambda i: np.mean([losses[i][j] for j in others]))
        p, y = predictions[best][held_out], d["y"]
        n_fit = int(len(y) * CALIBRATION_SHARE)
        a, b = recalibrate(_logit(p[:n_fit]), y[:n_fit])
        calibrated = 1 / (1 + np.exp(-(a * _logit(p[n_fit:]) + b)))
        results[held_out] = {
            "chosen on": others,
            "settings": {k: v for k, v in asdict(settings[best]).items() if k in GRID},
            "as trained": scores(y[n_fit:], p[n_fit:]),
            "recalibrated": scores(y[n_fit:], calibrated),
        }
        print(held_out, json.dumps(results[held_out]), flush=True)

    shipped = min(range(len(settings)), key=lambda i: np.mean(list(losses[i].values())))
    results["shipped settings"] = asdict(settings[shipped])
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "elo_tuning.json").write_text(json.dumps(results, indent=2))
    print("shipped:", results["shipped settings"])


if __name__ == "__main__":
    main()
