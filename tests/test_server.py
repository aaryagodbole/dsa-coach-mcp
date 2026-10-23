from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from dsa_coach_mcp.models import PlatformInfo, Problem, Profile, Submission
from dsa_coach_mcp.platforms import UserNotFoundError
from dsa_coach_mcp.server import create_server
from dsa_coach_mcp.store import ReviewStore

TODAY = date(2026, 1, 1)


def make_problem(problem_id: str, tags: list[str]) -> Problem:
    return Problem(
        platform="fake",
        problem_id=problem_id,
        title=problem_id,
        url=f"https://example.com/{problem_id}",
        tags=tags,
        level="easy",
    )


class FakeAdapter:
    name = "fake"

    def __init__(self) -> None:
        self.problems = [make_problem(f"p{i}", ["graph"]) for i in range(5)]

    async def describe(self) -> PlatformInfo:
        return PlatformInfo(name=self.name, tags=["graph"], levels=["easy"])

    async def profile(self, handle: str) -> Profile:
        if handle == "ghost":
            raise UserNotFoundError("fake user 'ghost' not found")
        submissions = [
            Submission(
                problem=self.problems[i],
                accepted=True,
                submitted_at=datetime(2026, 1, i + 1, tzinfo=UTC),
            )
            for i in range(2)
        ]
        return Profile(
            platform=self.name, handle=handle, solved_ids=["p0", "p1"], submissions=submissions
        )

    async def search(self, tags: list[str], level: str | None, limit: int) -> list[Problem]:
        return self.problems[:limit]


@pytest.fixture
def server(tmp_path: Path) -> MCPServer:
    return create_server(
        {"fake": FakeAdapter()}, ReviewStore(tmp_path / "coach.db"), today=lambda: TODAY
    )


async def call(server: MCPServer, name: str, **arguments: Any) -> Any:
    result = await server.call_tool(name, arguments)
    assert isinstance(result, CallToolResult)
    assert not result.is_error
    return result.structured_content


async def test_exposes_the_coaching_tools(server: MCPServer) -> None:
    names = {tool.name for tool in await server.list_tools()}

    assert names == {
        "list_platforms",
        "get_profile",
        "search_problems",
        "log_review",
        "revisions_due",
        "mistake_kinds",
        "list_mistakes",
        "mistake_patterns",
    }


async def test_prompts_only_name_tools_and_arguments_that_exist(server: MCPServer) -> None:
    tools = await server.list_tools()
    known = {t.name for t in tools} | {arg for t in tools for arg in t.input_schema["properties"]}

    for prompt in await server.list_prompts():
        text = (await server.get_prompt(prompt.name, {})).messages[0].content.text
        named = {word.strip(".,") for word in text.split() if "_" in word}
        assert named <= known, (prompt.name, named - known)


async def test_profile_returns_most_recent_submissions_first(server: MCPServer) -> None:
    profile = await call(server, "get_profile", platform="fake", handle="a", recent_submissions=1)

    assert [s["problem"]["problem_id"] for s in profile["submissions"]] == ["p1"]


async def test_search_skips_problems_the_handle_solved(server: MCPServer) -> None:
    found = await call(
        server, "search_problems", platform="fake", tags=["graph"], limit=3, exclude_solved_by="a"
    )

    assert [p["problem_id"] for p in found["result"]] == ["p2", "p3", "p4"]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"platform": "nope"}, "Unknown platform"),
        ({"platform": "fake", "tags": ["dp"]}, "Unknown fake tags"),
        ({"platform": "fake", "level": "hard"}, "Unknown fake level"),
    ],
)
async def test_search_rejects_values_the_platform_does_not_offer(
    server: MCPServer, arguments: dict[str, Any], message: str
) -> None:
    with pytest.raises(ToolError, match=message):
        await server.call_tool("search_problems", arguments)


async def test_platform_failures_reach_the_model_as_tool_errors(server: MCPServer) -> None:
    with pytest.raises(ToolError, match="not found"):
        await server.call_tool("get_profile", {"platform": "fake", "handle": "ghost"})


async def test_logged_review_is_due_after_its_interval(server: MCPServer) -> None:
    card = await call(
        server,
        "log_review",
        platform="fake",
        problem_id="p0",
        title="P0",
        url="https://example.com/p0",
        quality=5,
    )

    assert card["due"] == "2026-01-02"
    assert (await call(server, "revisions_due"))["result"] == []


@pytest.mark.parametrize(
    "bad",
    [{"problem_id": "  "}, {"title": ""}, {"url": "not a url"}, {"url": "ftp://x/y"}],
)
async def test_log_review_rejects_unusable_cards(server: MCPServer, bad: dict[str, str]) -> None:
    arguments = {
        "platform": "fake",
        "problem_id": "p0",
        "title": "P0",
        "url": "https://example.com/p0",
        "quality": 5,
        **bad,
    }

    with pytest.raises(ToolError):
        await server.call_tool("log_review", arguments)


async def test_overlapping_reviews_each_count(server: MCPServer) -> None:
    arguments = {
        "platform": "fake",
        "problem_id": "p0",
        "title": "P0",
        "url": "https://example.com/p0",
        "quality": 5,
    }

    await asyncio.gather(*(server.call_tool("log_review", arguments) for _ in range(3)))
    card = await call(server, "log_review", **arguments)

    assert card["repetitions"] == 4


REVIEW = {
    "platform": "fake",
    "problem_id": "p0",
    "title": "P0",
    "url": "https://example.com/p0",
    "quality": 2,
    "tags": ["graph"],
}


async def test_mistakes_logged_with_a_review_feed_the_journal(server: MCPServer) -> None:
    await call(
        server,
        "log_review",
        **REVIEW,
        mistakes=[
            {"kind": "missed empty input", "note": "crashed on []"},
            {"kind": "wrong traversal", "note": "used DFS where BFS gives shortest path"},
        ],
    )
    await call(
        server,
        "log_review",
        **REVIEW,
        mistakes=[
            {"kind": "missed empty input", "note": "again no guard for n = 0"},
        ],
    )

    kinds = (await call(server, "mistake_kinds"))["result"]
    patterns = await call(server, "mistake_patterns")
    journal = (await call(server, "list_mistakes", kind="missed empty input"))["result"]

    assert [(k["kind"], k["count"]) for k in kinds] == [
        ("missed empty input", 2),
        ("wrong traversal", 1),
    ]
    assert {"kind": "missed empty input", "key": "graph", "count": 2} in patterns["by_tag"]
    assert [m["note"] for m in journal] == ["again no guard for n = 0", "crashed on []"]
    assert journal[0]["title"] == "P0"


async def test_a_blank_mistake_is_rejected_and_nothing_is_saved(server: MCPServer) -> None:
    with pytest.raises(ToolError):
        await server.call_tool("log_review", {**REVIEW, "mistakes": [{"kind": " ", "note": "x"}]})

    assert (await call(server, "revisions_due"))["result"] == []
    assert (await call(server, "mistake_kinds"))["result"] == []


async def test_review_tags_must_come_from_the_platform(server: MCPServer) -> None:
    with pytest.raises(ToolError, match="Unknown fake tags"):
        await server.call_tool("log_review", {**REVIEW, "tags": ["made-up"]})


async def test_a_huge_lookback_means_all_time(server: MCPServer) -> None:
    await call(server, "log_review", **REVIEW, mistakes=[{"kind": "k", "note": "n"}])

    patterns = await call(server, "mistake_patterns", days=10**9)
    journal = (await call(server, "list_mistakes", days=10**9))["result"]

    assert [k["kind"] for k in patterns["kinds"]] == ["k"]
    assert len(journal) == 1


async def test_mistakes_can_be_read_for_one_problem(server: MCPServer) -> None:
    await call(server, "log_review", **REVIEW, mistakes=[{"kind": "k", "note": "on p0"}])
    await call(
        server,
        "log_review",
        **{**REVIEW, "problem_id": "p1", "title": "P1", "url": "https://example.com/p1"},
        mistakes=[{"kind": "k", "note": "on p1"}],
    )

    journal = (await call(server, "list_mistakes", platform="fake", problem_id="p0"))["result"]

    assert [m["note"] for m in journal] == ["on p0"]
