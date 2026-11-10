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
    hosts: tuple[str, ...] = ("example.com",)

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
        "link_account",
        "unlink_account",
        "search_problems",
        "log_review",
        "review_evidence",
        "revisions_due",
        "schedule_info",
        "personalize_schedule",
        "record_problem",
        "progress",
        "show_dashboard",
        "mistake_kinds",
        "list_mistakes",
        "mistake_patterns",
    }


async def test_every_tool_declares_all_four_behavior_hints(server: MCPServer) -> None:
    # An unset destructiveHint defaults to true in the spec, so a client or directory
    # reading hints alone would treat a read-only tool as destructive.
    for tool in await server.list_tools():
        hints = tool.annotations
        assert hints is not None, tool.name
        for hint in ("read_only_hint", "destructive_hint", "idempotent_hint", "open_world_hint"):
            assert isinstance(getattr(hints, hint), bool), (tool.name, hint)
        # Only the account tools overwrite or delete data, and just the saved username;
        # reads are also safe to repeat.
        if tool.name in {"link_account", "unlink_account"}:
            assert hints.destructive_hint is True, tool.name
            assert hints.idempotent_hint is True, tool.name
        else:
            assert hints.destructive_hint is False, tool.name
        if hints.read_only_hint:
            assert hints.idempotent_hint is True, tool.name


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


HACKERRANK = {
    "url": "https://www.hackerrank.com/challenges/ctci-ransom-note/problem",
    "title": "Hash Tables: Ransom Note",
    "tags": ["hash-tables", "hash-tables"],
    "level": "Easy",
}


async def test_any_platform_problem_is_recorded_and_reviewed(server: MCPServer) -> None:
    problem = await call(server, "record_problem", **HACKERRANK)

    assert (problem["platform"], problem["problem_id"]) == (
        "hackerrank.com",
        "challenges/ctci-ransom-note/problem",
    )
    assert (problem["tags"], problem["source"]) == (["hash-tables"], "reported")

    card = await call(
        server,
        "log_review",
        platform=problem["platform"],
        problem_id=problem["problem_id"],
        rating="hard",
        mistakes=[{"kind": "k", "note": "counted the wrong string"}],
    )
    platforms = (await call(server, "list_platforms"))["result"]
    progress = (await call(server, "progress"))["result"]
    journal = (await call(server, "list_mistakes", platform="hackerrank.com"))["result"]

    assert card["title"] == "Hash Tables: Ransom Note"
    reported = next(p for p in platforms if p["name"] == "hackerrank.com")
    assert (reported["source"], reported["tags"], reported["levels"]) == (
        "reported",
        ["hash-tables"],
        ["Easy"],
    )
    assert progress == [
        {
            "platform": "hackerrank.com",
            "source": "reported",
            "problems": 1,
            "reviews": 1,
            "due_now": 0,
        }
    ]
    assert journal[0]["tags"] == ["hash-tables"]


async def test_recording_the_same_url_again_updates_it(server: MCPServer) -> None:
    await call(server, "record_problem", **HACKERRANK)
    updated = await call(server, "record_problem", **{**HACKERRANK, "tags": ["strings"]})

    assert updated["tags"] == ["strings"]
    assert (
        len(
            [
                p
                for p in (await call(server, "list_platforms"))["result"]
                if p["source"] == "reported"
            ]
        )
        == 1
    )


async def test_a_host_with_an_adapter_is_sent_to_its_adapter(server: MCPServer) -> None:
    with pytest.raises(ToolError, match="platform 'fake'"):
        await server.call_tool("record_problem", {"url": "https://example.com/p0", "title": "p0"})


@pytest.mark.parametrize(
    "bad",
    [{"url": "ftp://x.org/p"}, {"url": "https://x.org/"}, {"title": " "}, {"tags": [""]}],
)
async def test_record_problem_rejects_unusable_input(
    server: MCPServer, bad: dict[str, Any]
) -> None:
    with pytest.raises(ToolError):
        await server.call_tool("record_problem", {**HACKERRANK, **bad})


async def test_reviewing_an_unrecorded_problem_says_to_record_it(server: MCPServer) -> None:
    with pytest.raises(ToolError, match="record_problem"):
        await server.call_tool(
            "log_review",
            {"platform": "codechef.com", "problem_id": "problems/X", "rating": "good"},
        )


async def test_recording_the_same_problem_from_a_variant_url_updates_it(
    server: MCPServer,
) -> None:
    first = await call(server, "record_problem", **HACKERRANK)
    await call(
        server,
        "log_review",
        platform=first["platform"],
        problem_id=first["problem_id"],
        rating="good",
    )

    updated = await call(
        server,
        "record_problem",
        **{**HACKERRANK, "url": HACKERRANK["url"] + "/", "title": "Ransom Note (fixed title)"},
    )

    assert updated["problem_id"] == first["problem_id"]
    assert updated["url"].endswith("/")
    progress = (await call(server, "progress"))["result"]
    assert progress[0]["problems"] == 1


async def test_a_recorded_title_change_reaches_the_review_card(
    server: MCPServer, clock: Clock
) -> None:
    problem = await call(server, "record_problem", **HACKERRANK)
    await call(
        server,
        "log_review",
        platform=problem["platform"],
        problem_id=problem["problem_id"],
        rating="again",
    )
    await call(server, "record_problem", **{**HACKERRANK, "title": "Renamed"})

    clock.at = NOW + timedelta(days=30)
    (card,) = (await call(server, "revisions_due"))["result"]

    assert card["title"] == "Renamed"


async def test_one_platform_down_leaves_the_others_listed(tmp_path: Path) -> None:
    class DownAdapter(FakeAdapter):
        name = "down"

        async def describe(self) -> PlatformInfo:
            raise UserNotFoundError("upstream timeout")

    server = create_server(
        {"fake": FakeAdapter(), "down": DownAdapter()},
        ReviewStore(tmp_path / "c.db"),
        now=Clock(),
        fuzz=False,
    )
    await call(server, "record_problem", **HACKERRANK)

    platforms = {p["name"]: p for p in (await call(server, "list_platforms"))["result"]}

    assert platforms["fake"]["tags"]
    assert platforms["down"]["limitations"] == ["Unavailable right now: upstream timeout"]
    assert "hackerrank.com" in platforms


async def test_dashboard_is_an_mcp_app_linked_from_its_tool(server: MCPServer) -> None:
    from mcp import Client

    from dsa_coach_mcp.server import DASHBOARD_URI, MCP_APP_MIME_TYPE

    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        resource = (await client.read_resource(DASHBOARD_URI)).contents[0]

    assert tools["show_dashboard"].meta == {"ui": {"resourceUri": DASHBOARD_URI}}
    assert resource.mime_type == MCP_APP_MIME_TYPE
    html = resource.text  # type: ignore[union-attr]
    assert "ui/initialize" in html
    assert "ui/notifications/tool-result" in html
    # Self-contained: hosts sandbox the view, and it loads nothing from elsewhere.
    assert "<script src" not in html
    assert "<link" not in html


async def test_dashboard_reports_progress_due_cards_and_patterns(
    server: MCPServer, clock: Clock
) -> None:
    await call(server, "log_review", **REVIEW, mistakes=[{"kind": "k", "note": "n"}])
    clock.at = NOW + timedelta(days=30)

    dashboard = await call(server, "show_dashboard")

    assert dashboard["progress"] == [
        {"platform": "fake", "source": "platform", "problems": 1, "reviews": 1, "due_now": 1}
    ]
    assert [c["problem_id"] for c in dashboard["due"]] == ["p0"]
    assert [k["kind"] for k in dashboard["patterns"]["kinds"]] == ["k"]
    insights = dashboard["insights"]
    assert insights["horizon_days"] == 14
    assert [(m["kind"], m["times"]) for m in insights["recovery"]] == [("k", 1)]
    (topic,) = insights["forecast"]
    assert topic["tag"] == "graph"
    assert topic["recall_later"] < topic["recall_now"]


async def test_review_evidence_reads_submissions_since_the_last_review(
    server: MCPServer, clock: Clock
) -> None:
    # The fake platform lists only accepted submissions, so it never guesses a rating.
    before = await call(server, "review_evidence", platform="fake", problem_id="p0", handle="a")
    await call(server, "log_review", **REVIEW)
    after = await call(server, "review_evidence", platform="fake", problem_id="p0", handle="a")

    assert (before["accepted"], before["suggested_rating"], before["since"]) == (True, None, None)
    assert "ask the user" in before["reason"]
    assert (after["submissions"], after["suggested_rating"]) == (0, None)
    assert after["since"] is not None


async def test_link_account_checks_the_handle_and_saves_it(server: MCPServer) -> None:
    stats = await call(server, "link_account", platform="fake", handle="alice")

    assert (stats["platform"], stats["handle"], stats["error"]) == ("fake", "alice", None)
    profile = await call(server, "get_profile", platform="fake")
    assert profile["handle"] == "alice"


async def test_link_account_rejects_an_unknown_handle_and_saves_nothing(server: MCPServer) -> None:
    with pytest.raises(ToolError, match="not found"):
        await server.call_tool("link_account", {"platform": "fake", "handle": "ghost"})

    assert (await call(server, "show_dashboard"))["accounts"] == []


async def test_linking_again_replaces_the_handle(server: MCPServer) -> None:
    await call(server, "link_account", platform="fake", handle="alice")
    await call(server, "link_account", platform="fake", handle="bob")

    assert [a["handle"] for a in (await call(server, "show_dashboard"))["accounts"]] == ["bob"]


async def test_a_handle_given_wins_over_the_linked_one(server: MCPServer) -> None:
    await call(server, "link_account", platform="fake", handle="alice")

    assert (await call(server, "get_profile", platform="fake", handle="bob"))["handle"] == "bob"


async def test_no_handle_and_none_linked_asks_for_one(server: MCPServer) -> None:
    for tool, args in [
        ("get_profile", {"platform": "fake"}),
        ("review_evidence", {"platform": "fake", "problem_id": "p0"}),
    ]:
        with pytest.raises(ToolError, match="link_account"):
            await server.call_tool(tool, args)


async def test_review_evidence_uses_the_linked_handle(server: MCPServer) -> None:
    await call(server, "link_account", platform="fake", handle="alice")

    evidence = await call(server, "review_evidence", platform="fake", problem_id="p0")

    assert evidence["accepted"] is True


async def test_unlink_account_forgets_the_handle(server: MCPServer) -> None:
    await call(server, "link_account", platform="fake", handle="alice")

    assert (await call(server, "unlink_account", platform="fake"))["result"] == "Unlinked fake."
    assert (await call(server, "unlink_account", platform="fake"))["result"] == (
        "No account was linked on fake."
    )
    assert (await call(server, "show_dashboard"))["accounts"] == []


async def test_dashboard_shows_each_linked_account_and_survives_a_broken_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dsa_coach_mcp import server as server_module

    class Broken(FakeAdapter):
        name = "broken"
        fail: Exception | None = None

        async def profile(self, handle: str) -> Profile:
            if self.fail:
                raise self.fail
            return await super().profile(handle)

    class Slow(FakeAdapter):
        name = "slow"
        hang = False

        async def profile(self, handle: str) -> Profile:
            if self.hang:
                await asyncio.sleep(10)
            return await super().profile(handle)

    broken, slow = Broken(), Slow()
    monkeypatch.setattr(server_module, "ACCOUNT_TIMEOUT_SECONDS", 0.05)
    store = ReviewStore(tmp_path / "c.db")
    app = create_server(
        {"fake": FakeAdapter(), "broken": broken, "slow": slow}, store, now=Clock(), fuzz=False
    )
    for platform in ("fake", "broken", "slow"):
        await call(app, "link_account", platform=platform, handle="alice")
    # A platform that was linked earlier but has no adapter now.
    store.link_account("gone", "alice", NOW)
    broken.fail = UserNotFoundError("fake user 'alice' not found")
    slow.hang = True

    accounts = {a["platform"]: a for a in (await call(app, "show_dashboard"))["accounts"]}

    assert sorted(accounts) == ["broken", "fake", "gone", "slow"]
    assert accounts["fake"]["error"] is None
    assert accounts["broken"]["error"] == "fake user 'alice' not found"
    assert "did not answer" in accounts["slow"]["error"]
    assert accounts["gone"]["error"] == "No adapter for this platform."


async def test_dashboard_reports_an_unreachable_platform(tmp_path: Path) -> None:
    import httpx

    class Offline(FakeAdapter):
        async def profile(self, handle: str) -> Profile:
            if handle == "offline":
                raise httpx.ConnectError("no route")
            return await super().profile(handle)

    store = ReviewStore(tmp_path / "c.db")
    app = create_server({"fake": Offline()}, store, now=Clock(), fuzz=False)
    store.link_account("fake", "offline", NOW)

    (account,) = (await call(app, "show_dashboard"))["accounts"]

    assert account["error"] == "fake is unreachable right now: no route"


def test_account_stats_lists_strong_struggling_and_barely_touched_tags() -> None:
    from dsa_coach_mcp.server import account_stats

    solved = {f"t{i}": 10 - i for i in range(8)} | {"zero": 0}
    stats = account_stats(
        Profile(
            platform="codeforces",
            handle="alice",
            level_summary={"rating": 1500},
            solved_by_tag=solved,
            unsolved_attempts_by_tag={"dp": 3, "graphs": 5, "math": 0},
            limitations=["note"],
        )
    )

    assert [t.tag for t in stats.strongest] == ["t0", "t1", "t2", "t3", "t4"]
    assert [(t.tag, t.count) for t in stats.struggling] == [("graphs", 5), ("dp", 3)]
    # Fewest first, never repeating a strongest tag, and never a tag with nothing solved.
    assert [t.tag for t in stats.least_practised] == ["t7", "t6", "t5"]
    assert (stats.levels, stats.limitations) == ({"rating": 1500}, ["note"])
