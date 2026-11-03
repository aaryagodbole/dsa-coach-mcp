"""The shipped skill must only send the agent to tools, arguments and prompts that exist."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from mcp import Client

from evals.fixture import build_server

SKILL = Path(__file__).parents[1] / "skills" / "dsa-coach" / "SKILL.md"


def test_frontmatter_is_valid() -> None:
    text = SKILL.read_text()
    assert text.startswith("---\n")
    front = yaml.safe_load(text.split("---\n")[1])

    assert front["name"] == "dsa-coach"
    # Claude Code truncates description + when_to_use at 1,536 characters.
    assert 0 < len(front["description"]) <= 1536


async def test_skill_names_only_real_tools_arguments_and_prompts(tmp_path: Path) -> None:
    server, _ = build_server(tmp_path / "coach.db")
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
        prompts = (await client.list_prompts()).prompts
    known = {t.name for t in tools} | {p.name for p in prompts}
    known |= {arg for t in tools for arg in t.input_schema["properties"]}

    named = set(re.findall(r"`([a-z]+(?:_[a-z]+)+)`", SKILL.read_text()))

    assert named, "the skill names no tools"
    assert named <= known, named - known
