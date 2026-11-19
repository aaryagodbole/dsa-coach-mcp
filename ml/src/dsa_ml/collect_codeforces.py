"""Collect a rating-stratified sample of Codeforces users and their full submission
histories, for training the solve-probability model.

Codeforces asks API clients to make at most one call every two seconds, so this runs
for about an hour per thousand users. It is resumable: users already saved are skipped.

    uv run python -m dsa_ml.collect_codeforces --users 2000
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import time
from pathlib import Path

import httpx

API = "https://codeforces.com/api"
DATA = Path(__file__).resolve().parents[2] / "data" / "raw" / "codeforces"
# Codeforces' published limit is one call per two seconds; stay just above it.
CALL_GAP_SECONDS = 2.1
# Rating bands to sample evenly from, so strong and weak users are both represented.
BANDS = [
    (0, 1000),
    (1000, 1200),
    (1200, 1400),
    (1400, 1600),
    (1600, 1900),
    (1900, 2100),
    (2100, 2400),
    (2400, 4000),
]


class Client:
    def __init__(self) -> None:
        self.http = httpx.Client(
            timeout=60, headers={"User-Agent": "dsa-coach-mcp-research (solve-probability model)"}
        )
        self.last = 0.0

    def call(self, method: str, **params: object) -> object:
        for attempt in range(5):
            wait = self.last + CALL_GAP_SECONDS - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            try:
                response = self.http.get(f"{API}/{method}", params=params)
                body = response.json()
            except (httpx.HTTPError, ValueError):
                time.sleep(5 * (attempt + 1))
                continue
            if body.get("status") == "OK":
                return body["result"]
            comment = body.get("comment", "")
            if "not found" in comment:
                raise LookupError(comment)
            # "Call limit exceeded" and temporary failures: back off and retry.
            time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"{method} failed after retries")


def sample_users(users: list[dict], per_band: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    chosen: list[str] = []
    for low, high in BANDS:
        band = [u["handle"] for u in users if low <= u.get("rating", 0) < high]
        rng.shuffle(band)
        chosen.extend(band[:per_band])
    return chosen


def keep(submission: dict) -> dict | None:
    """The fields the model needs; practice and virtual attempts count, others don't."""

    problem = submission.get("problem", {})
    if "contestId" not in problem or submission.get("verdict") in (None, "TESTING"):
        return None
    return {
        "problem": f"{problem['contestId']}{problem['index']}",
        "accepted": submission["verdict"] == "OK",
        "at": submission["creationTimeSeconds"],
        "kind": submission.get("author", {}).get("participantType"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    client = Client()
    (DATA / "users").mkdir(parents=True, exist_ok=True)

    problems_file = DATA / "problems.json"
    if not problems_file.exists():
        result = client.call("problemset.problems")
        problems_file.write_text(json.dumps(result["problems"]))  # type: ignore[index]

    sample_file = DATA / "sample.json"
    if sample_file.exists():
        handles = json.loads(sample_file.read_text())
    else:
        rated = client.call("user.ratedList", activeOnly="false", includeRetired="false")
        handles = sample_users(rated, args.users // len(BANDS), args.seed)  # type: ignore[arg-type]
        sample_file.write_text(json.dumps(handles))
    print(f"{len(handles)} users sampled", flush=True)

    for i, handle in enumerate(handles, 1):
        out = DATA / "users" / f"{handle}.json.gz"
        if out.exists():
            continue
        try:
            rows = client.call("user.status", handle=handle)
        except LookupError:
            rows = []
        kept = [k for s in rows if (k := keep(s)) is not None]  # type: ignore[union-attr]
        with gzip.open(out, "wt") as f:
            json.dump(kept, f)
        if i % 50 == 0:
            print(f"{i}/{len(handles)} users", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
