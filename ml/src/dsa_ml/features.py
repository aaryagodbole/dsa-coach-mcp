"""Features for each attempt, computed only from what happened before it.

Every feature of an attempt is built from the user's and the problem's history up to
that moment, never from later attempts, so a model evaluated on the newest attempts
cannot see the future. The online Elo here is also the model dsa-coach can ship: a
skill per user and a difficulty per problem, updated after every attempt.

    uv run python -m dsa_ml.features
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"
# Pseudo-counts that pull a short history towards the average: a user's first two
# attempts say little about them.
PRIOR = 5.0
# Elo step sizes. Problems see far more attempts than users, so they move slower.
K_USER = 0.4
K_PROBLEM = 0.05


def _elo(users: np.ndarray, problems: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, ...]:
    """Online Elo in logits: P(first try) = sigmoid(skill - difficulty + bias).

    Returns, for each attempt, the prediction and the skill and difficulty it was made
    with, all before the attempt's own outcome was seen."""

    skill = np.zeros(users.max() + 1)
    difficulty = np.zeros(problems.max() + 1)
    seen_user = np.zeros(users.max() + 1)
    seen_problem = np.zeros(problems.max() + 1)
    bias = np.log(y.mean() / (1 - y.mean()))
    pred = np.empty(len(y))
    skill_at = np.empty(len(y))
    diff_at = np.empty(len(y))
    for i in range(len(y)):
        u, q = users[i], problems[i]
        z = skill[u] - difficulty[q] + bias
        p = 1.0 / (1.0 + np.exp(-z))
        pred[i], skill_at[i], diff_at[i] = p, skill[u], difficulty[q]
        err = y[i] - p
        # Larger steps while a user or problem is new, so few attempts still move it.
        skill[u] += K_USER * err / (1 + 0.05 * seen_user[u])
        difficulty[q] -= max(K_PROBLEM, 1.0 / (1 + seen_problem[q])) * err
        seen_user[u] += 1
        seen_problem[q] += 1
    return pred, skill_at, diff_at


def _history(df: pd.DataFrame, key: str, prefix: str, base: float) -> pd.DataFrame:
    """Counts and smoothed first-try rate of ``key``'s earlier attempts."""

    g = df.groupby(key, sort=False)["y"]
    n = g.cumcount()
    hits = g.cumsum() - df["y"]
    return pd.DataFrame(
        {
            f"{prefix}_n": n,
            f"{prefix}_rate": (hits + PRIOR * base) / (n + PRIOR),
        },
        index=df.index,
    )


def build(attempts: pd.DataFrame) -> pd.DataFrame:
    out = []
    for source, df in attempts.groupby("source"):
        df = df.sort_values("at", kind="stable").reset_index(drop=True)
        df["y"] = (df["solved"] & (df["tries"] == 1)).astype(np.int8)
        base = df["y"].mean()
        users = df["user"].astype("category").cat.codes.to_numpy()
        problems = df["problem"].astype("category").cat.codes.to_numpy()
        pred, skill, diff = _elo(users, problems, df["y"].to_numpy(dtype=float))
        feats = pd.concat(
            [
                df[["source", "user", "problem", "at", "y"]],
                _history(df, "user", "user", base),
                _history(df, "problem", "problem", base),
            ],
            axis=1,
        )
        feats["elo_p"], feats["elo_skill"], feats["elo_difficulty"] = pred, skill, diff
        # How recently the user practised, and for how long they have.
        first_seen = df.groupby("user")["at"].transform("min")
        previous = df.groupby("user")["at"].shift()
        feats["user_days_active"] = (df["at"] - first_seen) / 86400
        feats["user_gap_days"] = ((df["at"] - previous) / 86400).fillna(-1)
        # The user's form: first-try rate over their last ten attempts.
        feats["user_recent_rate"] = (
            df.groupby("user")["y"]
            .transform(lambda s: s.shift().rolling(10, min_periods=1).mean())
            .fillna(base)
        )
        out.append(feats)
        print(f"{source}: {len(df)} attempts, base first-try rate {base:.3f}", flush=True)
    return pd.concat(out, ignore_index=True)


def main() -> None:
    attempts = pd.read_parquet(DATA / "attempts.parquet")
    feats = build(attempts)
    feats.to_parquet(DATA / "features.parquet", index=False)
    print(f"wrote {len(feats)} rows")


if __name__ == "__main__":
    main()
