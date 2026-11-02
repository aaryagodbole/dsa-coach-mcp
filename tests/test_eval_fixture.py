from __future__ import annotations

import json
from pathlib import Path

from mcp import Client

from evals.fixture import build_server, seed_history

TASKS = json.loads((Path(__file__).parents[1] / "evals" / "tasks.json").read_text())["tasks"]


async def test_every_task_names_only_real_tools_and_arguments(tmp_path: Path) -> None:
    server, _ = build_server(tmp_path / "coach.db")
    async with Client(server) as client:
        tools = {
            t.name: set(t.input_schema["properties"]) for t in (await client.list_tools()).tools
        }

    for task in TASKS:
        for expectation in task.get("expect", []):
            for name in [expectation["tool"], *expectation.get("alternatives", [])]:
                assert name in tools, (task["id"], name)
            assert set(expectation.get("args", {})) <= tools[expectation["tool"]], task["id"]
        assert set(task.get("forbid", [])) - {"*"} <= set(tools), task["id"]


async def test_the_seeded_world_has_due_revisions_and_labels_to_reuse(tmp_path: Path) -> None:
    server, clock = build_server(tmp_path / "coach.db")
    await seed_history(server, clock)

    async with Client(server) as client:
        due = (await client.call_tool("revisions_due", {})).structured_content
        kinds = (await client.call_tool("mistake_kinds", {})).structured_content

    assert due is not None
    assert due["result"]
    assert kinds is not None
    assert {k["kind"] for k in kinds["result"]} == {"missed cycle detection", "missed edge case"}
