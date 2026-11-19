"""Turn each judge's raw submissions into one table of attempts.

An attempt is one user's history with one problem: when they first submitted, whether
they ever got it accepted, and after how many submissions. That is the unit the
solve-probability model predicts: "if this user tries this problem, will they solve it?"

    uv run python -m dsa_ml.attempts
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
OUT = Path(__file__).resolve().parents[2] / "data" / "attempts.parquet"
COLUMNS = ["source", "user", "problem", "at", "solved", "tries"]
# 2018-01-01 UTC; see codenet().
AIZU_COMPLETE_UNTIL = 1514764800


def _attempts(subs: pd.DataFrame, source: str) -> pd.DataFrame:
    """One row per (user, problem) from rows of user, problem, at, accepted."""

    subs = subs.sort_values("at")
    first_ok = subs[subs["accepted"]].groupby(["user", "problem"])["at"].min().rename("ok_at")
    subs = subs.join(first_ok, on=["user", "problem"])
    # Submissions up to and including the first accepted one: retries after solving
    # are practice, not difficulty.
    deciding = subs[subs["ok_at"].isna() | (subs["at"] <= subs["ok_at"])]
    out = deciding.groupby(["user", "problem"]).agg(
        at=("at", "min"), solved=("accepted", "any"), tries=("at", "size")
    )
    out = out.reset_index()
    out.insert(0, "source", source)
    return out[COLUMNS]


def codenet() -> pd.DataFrame:
    meta = RAW / "codenet" / "Project_CodeNet" / "metadata"
    problems = pd.read_csv(meta / "problem_list.csv")
    frames = []
    for dataset in ("AtCoder", "AIZU"):
        ids = problems.loc[problems.dataset == dataset, "id"]
        rows = [
            pd.read_csv(meta / f"{pid}.csv", usecols=["problem_id", "user_id", "date", "status"])
            for pid in ids
            if (meta / f"{pid}.csv").exists()
        ]
        subs = pd.concat(rows, ignore_index=True)
        subs = subs.rename(columns={"problem_id": "problem", "user_id": "user", "date": "at"})
        # Compile errors and judge failures say nothing about solving the problem.
        subs = subs[~subs.status.isin(["Compile Error", "Judge Not Available"])]
        if dataset == "AIZU":
            # CodeNet's AIZU data stops recording failed submissions during 2018: the
            # share accepted is 42-46% every year to 2017, then 54%, 85% and 100%.
            subs = subs[subs["at"] < AIZU_COMPLETE_UNTIL]
        subs["accepted"] = subs.status == "Accepted"
        frames.append(_attempts(subs[["user", "problem", "at", "accepted"]], dataset.lower()))
    return pd.concat(frames, ignore_index=True)


def codeforces() -> pd.DataFrame:
    rows = []
    for path in (RAW / "codeforces" / "users").glob("*.json.gz"):
        user = path.name.removesuffix(".json.gz")
        with gzip.open(path, "rt") as f:
            for s in json.load(f):
                rows.append((user, s["problem"], s["at"], s["accepted"]))
    subs = pd.DataFrame(rows, columns=["user", "problem", "at", "accepted"])
    return _attempts(subs, "codeforces")


def main() -> None:
    frames = [codenet()]
    if (RAW / "codeforces" / "users").exists():
        frames.append(codeforces())
    attempts = pd.concat(frames, ignore_index=True)
    attempts.to_parquet(OUT, index=False)
    summary = attempts.groupby("source").agg(
        attempts=("solved", "size"),
        users=("user", "nunique"),
        problems=("problem", "nunique"),
        solve_rate=("solved", "mean"),
    )
    print(summary.to_string())


if __name__ == "__main__":
    main()
