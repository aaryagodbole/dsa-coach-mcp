"""Features for each attempt, computed only from what happened before it.

Every feature of an attempt is built from the user's and the problem's history up to
that moment, never from later attempts, so a model evaluated on the newest attempts
cannot see the future. The online Elo here is also the model dsa-coach can ship: a
skill per user and a difficulty per problem, updated after every attempt.

    uv run python -m dsa_ml.features
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import elo
from .topics import topic_ids

DATA = Path(__file__).resolve().parents[2] / "data"
# Pseudo-counts that pull a short history towards the average: a user's first two
# attempts say little about them.
PRIOR = 5.0
# Starting first-try rate for smoothing a short history: the training judges' rate,
# never the evaluated judge's own (which would leak its future).
START_RATE = elo.Settings().start_rate


def published_difficulty() -> dict[str, dict[str, float]]:
    """Each judge's own published rating for its problems (Elo-style: Codeforces
    ratings, AtCoder Problems' difficulty). Judges with none (AIZU) are absent."""

    raw = DATA / "raw"
    out: dict[str, pd.Series] = {}
    cf = json.loads((raw / "codeforces" / "problems.json").read_text())
    out["codeforces"] = pd.Series(
        {f"{p['contestId']}{p['index']}": p["rating"] for p in cf if "rating" in p}
    )
    atcoder = raw / "atcoder"
    models = json.loads((atcoder / "problem-models.json").read_text())
    contests = {
        c["id"]: c["title"].strip() for c in json.loads((atcoder / "contests.json").read_text())
    }
    by_name = {}
    for p in json.loads((atcoder / "problems.json").read_text()):
        title = re.sub(r"^[A-Za-z0-9]+\.\s*", "", p["title"]).strip()
        difficulty = models.get(p["id"], {}).get("difficulty")
        if difficulty is not None:
            by_name[(contests.get(p["contest_id"], ""), title)] = difficulty
    # CodeNet names AtCoder problems "<contest title> - <problem title>".
    codenet = pd.read_csv(raw / "codenet" / "Project_CodeNet" / "metadata" / "problem_list.csv")
    rows = {}
    for pid, name in codenet.loc[codenet["dataset"] == "AtCoder", ["id", "name"]].itertuples(
        index=False
    ):
        contest, _, title = name.partition(" - ")
        if (found := by_name.get((contest.strip(), title.strip()))) is not None:
            rows[pid] = found
    out["atcoder"] = pd.Series(rows)
    return {source: series.to_dict() for source, series in out.items()}


def codeforces_topics() -> dict[str, list[int]]:
    cf = json.loads((DATA / "raw" / "codeforces" / "problems.json").read_text())
    return {f"{p['contestId']}{p['index']}": topic_ids("codeforces", p.get("tags", [])) for p in cf}


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
    published = published_difficulty()
    topics_of = {"codeforces": codeforces_topics()}
    out = []
    for source, df in attempts.groupby("source"):
        source = str(source)
        df = df.sort_values("at", kind="stable").reset_index(drop=True)
        df["y"] = (df["solved"] & (df["tries"] == 1)).astype(np.int8)
        y = df["y"].to_numpy(dtype=float)
        users = df["user"].astype("category").cat.codes.to_numpy()
        problem_cat = df["problem"].astype("category")
        problems = problem_cat.cat.codes.to_numpy()
        names = list(problem_cat.cat.categories)
        rating_of = published.get(source, {})
        rating = np.array([rating_of.get(p, np.nan) for p in names], dtype=float)
        topics = [topics_of.get(source, {}).get(p, []) for p in names]
        no_topics = [[] for _ in names]

        plain = elo.run(users, problems, no_topics, y, rating)
        topical = elo.run(users, problems, topics, y, rating)
        feats = pd.concat(
            [
                df[["source", "user", "problem", "at", "y"]],
                _history(df, "user", "user", START_RATE),
                _history(df, "problem", "problem", START_RATE),
            ],
            axis=1,
        )
        feats["elo_p"] = plain["p"]
        feats["topic_elo_p"] = topical["p"]
        feats["elo_skill"] = topical["skill"]
        feats["elo_topic_skill"] = topical["topic_skill"]
        feats["elo_difficulty"] = topical["difficulty"]
        feats["elo_logit"] = np.log(
            np.clip(topical["p"], 1e-4, 1 - 1e-4) / np.clip(1 - topical["p"], 1e-4, 1)
        )
        # Published difficulty as a percentile within its judge, and the user's level on
        # the same scale: the mean percentile of problems they solved first try before.
        pct = pd.Series(rating_of, dtype=float).rank(pct=True)
        feats["pub_pct"] = df["problem"].map(pct).astype(float)
        solved_pct = feats["pub_pct"].where(df["y"] == 1)
        counts = solved_pct.notna().groupby(df["user"]).cumsum() - solved_pct.notna()
        sums = solved_pct.fillna(0).groupby(df["user"]).cumsum() - solved_pct.fillna(0)
        feats["user_level_pct"] = (sums / counts).where(counts > 0)
        feats["pct_gap"] = feats["pub_pct"] - feats["user_level_pct"]
        # How recently the user practised, and for how long they have.
        first_seen = df.groupby("user")["at"].transform("min")
        previous = df.groupby("user")["at"].shift()
        feats["user_days_active"] = (df["at"] - first_seen) / 86400
        feats["user_gap_days"] = ((df["at"] - previous) / 86400).fillna(-1)
        # The user's form: first-try rate over their last ten attempts.
        feats["user_recent_rate"] = (
            df.groupby("user")["y"]
            .transform(lambda s: s.shift().rolling(10, min_periods=1).mean())
            .fillna(START_RATE)
        )
        out.append(feats)
        print(f"{source}: {len(df)} attempts, first-try rate {y.mean():.3f}", flush=True)
    return pd.concat(out, ignore_index=True)


def main() -> None:
    attempts = pd.read_parquet(DATA / "attempts.parquet")
    feats = build(attempts)
    feats.to_parquet(DATA / "features.parquet", index=False)
    print(f"wrote {len(feats)} rows")


if __name__ == "__main__":
    main()
