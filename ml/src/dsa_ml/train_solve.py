"""Train and evaluate the solve-probability model: will this user solve this problem on
their first try?

Split by time within each judge: the oldest 80% of attempts train, the newest 20% test.
Every feature is computed from earlier attempts only (see features.py), so the test set
is a fair stand-in for predicting tomorrow's attempts.

    uv run python -m dsa_ml.train_solve
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score

DATA = Path(__file__).resolve().parents[2] / "data"
ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"
TEST_SHARE = 0.2
SEED = 7
FEATURES = [
    "user_n",
    "user_rate",
    "problem_n",
    "problem_rate",
    "elo_skill",
    "elo_difficulty",
    "user_days_active",
    "user_gap_days",
    "user_recent_rate",
]


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error: how far predicted chances are from what happened."""

    edges = np.linspace(0, 1, bins + 1)
    which = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    total = 0.0
    for b in range(bins):
        mask = which == b
        if mask.any():
            total += mask.mean() * abs(y[mask].mean() - p[mask].mean())
    return float(total)


def split(feats: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cut = feats.groupby("source")["at"].transform(lambda s: s.quantile(1 - TEST_SHARE))
    return feats[feats["at"] < cut], feats[feats["at"] >= cut]


def scores(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {
        "auc": round(float(roc_auc_score(y, p)), 4),
        "log_loss": round(float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6))), 4),
        "ece": round(ece(y, p), 4),
    }


def main() -> None:
    feats = pd.read_parquet(DATA / "features.parquet")
    for source in feats["source"].unique():
        feats[f"is_{source}"] = (feats["source"] == source).astype(np.int8)
    sources = sorted(feats["source"].unique())
    columns = FEATURES + [f"is_{s}" for s in sources]
    train, test = split(feats)
    print(f"train {len(train)}  test {len(test)}", flush=True)

    sample = train.sample(min(len(train), 3_000_000), random_state=SEED)
    y_train = sample["y"].to_numpy()

    linear_cols = ["user_rate", "problem_rate", "user_recent_rate"]

    def linear_x(df: pd.DataFrame) -> np.ndarray:
        x = [_logit(df[c].to_numpy()) for c in linear_cols]
        x += [df["elo_skill"].to_numpy(), df["elo_difficulty"].to_numpy()]
        x += [np.log1p(df["user_n"].to_numpy())]
        x += [df[f"is_{s}"].to_numpy() for s in sources]
        return np.column_stack(x)

    logreg = LogisticRegression(max_iter=1000).fit(linear_x(sample), y_train)

    booster = lgb.train(
        {
            "objective": "binary",
            "learning_rate": 0.05,
            "num_leaves": 63,
            "min_data_in_leaf": 200,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
            "seed": SEED,
            "verbose": -1,
        },
        lgb.Dataset(sample[columns], y_train),
        num_boost_round=400,
    )

    predictions = {
        "problem only (its first-try rate)": test["problem_rate"].to_numpy(),
        "user only (their first-try rate)": test["user_rate"].to_numpy(),
        "online Elo": test["elo_p"].to_numpy(),
        "logistic regression": logreg.predict_proba(linear_x(test))[:, 1],
        "LightGBM": booster.predict(test[columns]),
    }

    results: dict[str, dict] = {}
    for name, p in predictions.items():
        results[name] = {"all": scores(test["y"].to_numpy(), p)}
        for source in sources:
            mask = (test["source"] == source).to_numpy()
            results[name][source] = scores(test["y"].to_numpy()[mask], p[mask])
        # Cold start: users with fewer than five earlier attempts.
        cold = (test["user_n"] < 5).to_numpy()
        results[name]["new users (<5 attempts)"] = scores(test["y"].to_numpy()[cold], p[cold])

    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "solve_results.json").write_text(json.dumps(results, indent=2))
    booster.save_model(str(ARTIFACTS / "solve_lightgbm.txt"))
    importance = dict(
        zip(columns, booster.feature_importance("gain").round().astype(int).tolist(), strict=True)
    )
    (ARTIFACTS / "solve_importance.json").write_text(json.dumps(importance, indent=2))

    rows = []
    for name, by in results.items():
        for part, s in by.items():
            rows.append({"model": name, "test set": part, **s})
    table = pd.DataFrame(rows)
    print(table.pivot(index="model", columns="test set", values="auc").round(3).to_string())
    print()
    print(table[table["test set"] == "all"].set_index("model")[["auc", "log_loss", "ece"]])
    print(
        "\ntest sizes:",
        test["source"].value_counts().to_dict(),
        "cold:",
        int((test["user_n"] < 5).sum()),
    )


if __name__ == "__main__":
    main()
