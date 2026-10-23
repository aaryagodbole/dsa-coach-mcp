from __future__ import annotations

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


async def test_exposes_the_five_tools(server: MCPServer) -> None:
    names = {tool.name for tool in await server.list_tools()}

    assert names == {
        "list_platforms",
        "get_profile",
        "search_problems",
        "log_review",
        "revisions_due",
    }


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
