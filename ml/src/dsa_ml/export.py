"""Export the shipped models into dsa-coach's package, in a form plain Python can read.

The recall model's trees become flat arrays (no LightGBM needed to predict); the solve
model is topic Elo's settings and the shared topic list. Export checks that the plain
reader reproduces LightGBM's predictions before writing.

    uv run python -m dsa_ml.export
"""

from __future__ import annotations

import gzip
import json
import math
from dataclasses import asdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from . import elo
from .topics import TOPICS
from .train_recall import DEPLOYABLE

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"
DATA = Path(__file__).resolve().parents[2] / "data"
OUT = ROOT / "src" / "dsa_coach_mcp" / "trained"


def flatten(node: dict, nodes: list) -> int:
    """Append a tree in preorder. Internal: [feature, threshold, left, right]; leaf:
    [value]. Returns the node's index."""

    index = len(nodes)
    if "leaf_value" in node:
        nodes.append([round(node["leaf_value"], 7)])
        return index
    if node["decision_type"] != "<=":
        raise ValueError(f"unsupported split {node['decision_type']}")
    nodes.append(None)
    left = flatten(node["left_child"], nodes)
    right = flatten(node["right_child"], nodes)
    nodes[index] = [node["split_feature"], node["threshold"], left, right]
    return index


def predict(model: dict, row: list[float]) -> float:
    total = 0.0
    for nodes in model["trees"]:
        i = 0
        while len(nodes[i]) == 4:
            feature, threshold, left, right = nodes[i]
            i = left if row[feature] <= threshold else right
        total += nodes[i][0]
    return 1 / (1 + math.exp(-total))


def export_recall() -> dict:
    booster = lgb.Booster(model_file=str(ARTIFACTS / "recall_small.txt"))
    dump = booster.dump_model()
    assert dump["feature_names"] == DEPLOYABLE, dump["feature_names"]
    trees = []
    for info in dump["tree_info"]:
        nodes: list = []
        flatten(info["tree_structure"], nodes)
        trees.append(nodes)
    model = {"features": DEPLOYABLE, "trees": trees}
    sample = pd.read_parquet(DATA / "recall_events.parquet").sample(2000, random_state=1)
    expected = booster.predict(sample[DEPLOYABLE])
    got = np.array([predict(model, r) for r in sample[DEPLOYABLE].to_numpy().tolist()])
    worst = float(np.max(np.abs(expected - got)))
    assert worst < 1e-6, worst
    print(f"recall: {len(trees)} trees, plain reader matches LightGBM (max diff {worst:.1e})")
    return model


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    recall = export_recall()
    with gzip.open(OUT / "recall.json.gz", "wt") as f:
        json.dump(recall, f, separators=(",", ":"))
    tuning = json.loads((ARTIFACTS / "elo_tuning.json").read_text())
    solve = {
        "settings": tuning["shipped settings"],
        "elo_to_logit": elo.ELO_TO_LOGIT,
        "topics": {
            t: {j: list(tags) for j, tags in judges.items()} for t, judges in TOPICS.items()
        },
    }
    (OUT / "solve.json").write_text(json.dumps(solve, indent=1))
    defaults = asdict(elo.Settings())
    print("solve settings:", solve["settings"], "(defaults", defaults, ")")
    for f in sorted(OUT.iterdir()):
        print(f.name, f.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
