from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import fsrs
import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult

from dsa_coach_mcp.models import PlatformInfo, Problem, Profile, Submission
from dsa_coach_mcp.platforms import ProblemNotFoundError, UserNotFoundError
from dsa_coach_mcp.server import create_server
from dsa_coach_mcp.store import ReviewStore

NOW = datetime(2026, 1, 1, 9, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.at = NOW

    def __call__(self) -> datetime:
        return self.at


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
        # The last problem carries a tag the platform's own tag list leaves out, as
        # LeetCode's does.
        self.problems = [make_problem(f"p{i}", ["graph"]) for i in range(4)]
        self.problems.append(make_problem("p4", ["graph", "unlisted"]))

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
        return [p for p in self.problems if set(tags) <= set(p.tags)][:limit]

    async def problem(self, problem_id: str) -> Problem:
        for problem in self.problems:
            if problem.problem_id == problem_id:
                return problem
        raise ProblemNotFoundError(f"fake problem '{problem_id}' not found")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def server(tmp_path: Path, clock: Clock) -> MCPServer:
    return create_server(
        {"fake": FakeAdapter()}, ReviewStore(tmp_path / "coach.db"), now=clock, fuzz=False
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
        "schedule_info",
        "personalize_schedule",
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
        ({"platform": "fake", "tags": ["dp"]}, "not in its tag list"),
        ({"platform": "fake", "level": "hard"}, "Unknown fake level"),
    ],
)
async def test_search_rejects_values_the_platform_does_not_offer(
    server: MCPServer, arguments: dict[str, Any], message: str
) -> None:
    with pytest.raises(ToolError, match=message):
        await server.call_tool("search_problems", arguments)


async def test_a_tag_missing_from_the_platform_list_still_searches(server: MCPServer) -> None:
    found = await call(server, "search_problems", platform="fake", tags=["unlisted"])

    assert [p["problem_id"] for p in found["result"]] == ["p4"]


async def test_platform_failures_reach_the_model_as_tool_errors(server: MCPServer) -> None:
    with pytest.raises(ToolError, match="not found"):
        await server.call_tool("get_profile", {"platform": "fake", "handle": "ghost"})


async def test_a_review_is_scheduled_days_ahead_and_falls_due(
    server: MCPServer, clock: Clock
) -> None:
    card = await call(server, "log_review", platform="fake", problem_id="p0", rating="good")

    due = datetime.fromisoformat(card["due"])
    assert due - NOW >= timedelta(days=1)
    assert (card["title"], card["url"], card["reviews"]) == ("p0", "https://example.com/p0", 1)
    assert (await call(server, "revisions_due"))["result"] == []

    clock.at = due
    (overdue,) = (await call(server, "revisions_due"))["result"]
    assert overdue["problem_id"] == "p0"
    assert 0 < overdue["retrievability"] < 1


async def test_an_easier_recall_waits_longer(server: MCPServer) -> None:
    hard = await call(server, "log_review", platform="fake", problem_id="p0", rating="hard")
    easy = await call(server, "log_review", platform="fake", problem_id="p1", rating="easy")

    assert easy["due"] > hard["due"]


async def test_revisions_lead_with_what_the_user_is_most_likely_to_forget(
    server: MCPServer, clock: Clock
) -> None:
    await call(server, "log_review", platform="fake", problem_id="p0", rating="easy")
    await call(server, "log_review", platform="fake", problem_id="p1", rating="again")

    clock.at = NOW + timedelta(days=60)
    due = (await call(server, "revisions_due"))["result"]

    assert [c["problem_id"] for c in due] == ["p1", "p0"]
    assert due[0]["retrievability"] < due[1]["retrievability"]


async def test_schedule_info_reports_default_parameters_until_personalised(
    server: MCPServer,
) -> None:
    await call(server, "log_review", platform="fake", problem_id="p0", rating="good")

    info = await call(server, "schedule_info")

    assert (info["personalised"], info["reviews"]) == (False, 1)
    assert len(info["parameters"]) > 0


async def test_personalising_without_the_optimizer_says_how_to_get_it(
    server: MCPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A None entry makes importing the module fail, as it does without the extra.
    monkeypatch.setitem(sys.modules, "fsrs.optimizer", None)
    monkeypatch.delitem(vars(fsrs), "Optimizer", raising=False)

    with pytest.raises(ToolError, match=r"dsa-coach-mcp\[optimizer\]"):
        await server.call_tool("personalize_schedule", {})


@pytest.mark.parametrize("problem_id", ["  ", "no-such-problem"])
async def test_log_review_needs_a_problem_the_platform_has(
    server: MCPServer, problem_id: str
) -> None:
    with pytest.raises(ToolError):
        await server.call_tool(
            "log_review", {"platform": "fake", "problem_id": problem_id, "rating": "good"}
        )

    assert (await call(server, "revisions_due", limit=10))["result"] == []


async def test_overlapping_reviews_each_count(server: MCPServer) -> None:
    arguments = {"platform": "fake", "problem_id": "p0", "rating": "good"}

    await asyncio.gather(*(server.call_tool("log_review", arguments) for _ in range(3)))
    card = await call(server, "log_review", **arguments)

    assert card["reviews"] == 4


REVIEW = {"platform": "fake", "problem_id": "p0", "rating": "hard"}


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
    assert journal[0]["title"] == "p0"


async def test_a_blank_mistake_is_rejected_and_nothing_is_saved(server: MCPServer) -> None:
    with pytest.raises(ToolError):
        await server.call_tool("log_review", {**REVIEW, "mistakes": [{"kind": " ", "note": "x"}]})

    assert (await call(server, "revisions_due"))["result"] == []
    assert (await call(server, "mistake_kinds"))["result"] == []


async def test_journal_tags_are_the_platform_tags_of_the_problem(server: MCPServer) -> None:
    await call(
        server,
        "log_review",
        **{**REVIEW, "problem_id": "p4"},
        mistakes=[{"kind": "k", "note": "n"}],
    )

    journal = (await call(server, "list_mistakes"))["result"]

    assert journal[0]["tags"] == ["graph", "unlisted"]


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
        **{**REVIEW, "problem_id": "p1"},
        mistakes=[{"kind": "k", "note": "on p1"}],
    )

    journal = (await call(server, "list_mistakes", platform="fake", problem_id="p0"))["result"]

    assert [m["note"] for m in journal] == ["on p0"]


async def test_an_unfitted_result_is_not_saved_as_personal(
    server: MCPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fsrs.scheduler import DEFAULT_PARAMETERS

    from dsa_coach_mcp import scheduling

    monkeypatch.setattr(scheduling, "optimize", lambda logs: list(DEFAULT_PARAMETERS))
    await call(server, "log_review", platform="fake", problem_id="p0", rating="good")

    with pytest.raises(ToolError, match="too few"):
        await server.call_tool("personalize_schedule", {})
    assert (await call(server, "schedule_info"))["personalised"] is False


async def test_the_most_at_risk_card_leads_even_beyond_the_limit(
    server: MCPServer, clock: Clock
) -> None:
    # p0 falls due first but is better remembered; p1 falls due later and is shakier.
    p0 = await call(server, "log_review", platform="fake", problem_id="p0", rating="good")
    clock.at = NOW + timedelta(days=10)
    p1 = await call(server, "log_review", platform="fake", problem_id="p1", rating="again")
    assert p0["due"] < p1["due"]

    clock.at = NOW + timedelta(days=40)
    (first,) = (await call(server, "revisions_due", limit=1))["result"]

    assert first["problem_id"] == "p1"
