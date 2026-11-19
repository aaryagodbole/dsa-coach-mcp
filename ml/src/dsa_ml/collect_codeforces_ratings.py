"""Collect each sampled Codeforces user's rating history (one call per user), so every
attempt can carry the user's contest rating at that moment. Run after
collect_codeforces; resumable.

    uv run python -m dsa_ml.collect_codeforces_ratings
"""

from __future__ import annotations

import gzip
import json

from .collect_codeforces import DATA, Client


def main() -> None:
    client = Client()
    out_dir = DATA / "ratings"
    out_dir.mkdir(exist_ok=True)
    handles = json.loads((DATA / "sample.json").read_text())
    for i, handle in enumerate(handles, 1):
        out = out_dir / f"{handle}.json.gz"
        if out.exists():
            continue
        try:
            changes = client.call("user.rating", handle=handle)
        except LookupError:
            changes = []
        kept = [
            {"at": c["ratingUpdateTimeSeconds"], "rating": c["newRating"]}
            for c in changes  # type: ignore[union-attr]
        ]
        with gzip.open(out, "wt") as f:
            json.dump(kept, f)
        if i % 100 == 0:
            print(f"{i}/{len(handles)} users", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
