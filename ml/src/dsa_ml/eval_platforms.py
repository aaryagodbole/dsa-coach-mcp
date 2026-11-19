"""Leave-one-platform-out evaluation: train on every judge but one, test on the one left
out, to measure how the model does on a platform it has never seen.

Two-stage calibration (as in few-shot recalibration under domain shift): each model is
first used as trained, then corrected with two numbers (a slope and an offset on the
logit) fitted on the new platform's earliest attempts only, pulled towards no
correction so a small sample cannot over-correct. Everything is scored on the later
attempts, which neither stage saw.

    uv run python -m dsa_ml.eval_platforms
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .train_solve import FEATURES, SEED, scores

DATA = Path(__file__).resolve().parents[2] / "data"
ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"
# Share of the new platform's attempts, earliest first, used for the second stage.
CALIBRATION_SHARE = 0.05
# How strongly the correction is pulled towards none (slope 1, offset 0).
SHRINK = 50.0


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def recalibrate(z: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Slope and offset for sigmoid(a * z + b), by Newton's method on log-loss with a
    penalty towards a = 1, b = 0."""

    a, b = 1.0, 0.0
    for _ in range(25):
        p = 1 / (1 + np.exp(-(a * z + b)))
        g = np.array([np.sum((p - y) * z) + SHRINK * (a - 1), np.sum(p - y) + SHRINK * b])
        w = p * (1 - p)
        h = np.array(
            [[np.sum(w * z * z) + SHRINK, np.sum(w * z)], [np.sum(w * z), np.sum(w) + SHRINK]]
        )
        a, b = np.array([a, b]) - np.linalg.solve(h, g)
    return float(a), float(b)


def main() -> None:
    feats = pd.read_parquet(DATA / "features.parquet")
    results = {}
    for held_out in sorted(feats["source"].unique()):
        train = feats[feats["source"] != held_out]
        test = feats[feats["source"] == held_out].sort_values("at", kind="stable")
        sample = train.sample(min(len(train), 2_000_000), random_state=SEED)
        booster = lgb.train(
            {
                "objective": "binary",
                "learning_rate": 0.05,
                "num_leaves": 63,
                "min_data_in_leaf": 200,
                "seed": SEED,
                "verbose": -1,
            },
            lgb.Dataset(sample[FEATURES], sample["y"]),
            300,
        )
        y = test["y"].to_numpy()
        n_fit = int(len(test) * CALIBRATION_SHARE)
        raw = {
            "problem only": test["problem_rate"].to_numpy(),
            "online Elo": test["elo_p"].to_numpy(),
            "topic Elo": test["topic_elo_p"].to_numpy(),
            "LightGBM": booster.predict(test[FEATURES]),
        }
        entry: dict[str, object] = {
            "trained on": sorted(set(feats["source"]) - {held_out}),
            "scored attempts": len(test) - n_fit,
        }
        for name, p in raw.items():
            z = _logit(p)
            a, b = recalibrate(z[:n_fit], y[:n_fit])
            calibrated = 1 / (1 + np.exp(-(a * z[n_fit:] + b)))
            entry[name] = {
                "as trained": scores(y[n_fit:], p[n_fit:]),
                "recalibrated": scores(y[n_fit:], calibrated),
            }
        results[held_out] = entry
        print(f"\n== held out: {held_out} ({len(test) - n_fit} attempts scored)")
        for name in raw:
            r = entry[name]
            print(
                f"  {name:14s} as trained {r['as trained']}  recalibrated {r['recalibrated']}"  # type: ignore[index]
            )
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "platform_results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
