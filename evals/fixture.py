"""A deterministic world for agent evals: one fixture platform, a seeded store and a
fixed clock, so every run sees the same data and nothing touches the network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from dsa_coach_mcp.models import PlatformInfo, Problem, Profile
from dsa_coach_mcp.platforms import ProblemNotFoundError, UserNotFoundError
from dsa_coach_mcp.server import create_server
from dsa_coach_mcp.store import ReviewStore

PLATFORM = "practice"
HANDLE = "learner"
START = datetime(2026, 3, 1, 9, tzinfo=UTC)

PROBLEMS = [
    Problem(
        platform=PLATFORM,
        problem_id=pid,
        title=title,
        url=f"https://practice.invalid/{pid}",
        tags=tags,
        level=level,
    )
    for pid, title, tags, level in [
        ("two-sum", "Two Sum", ["array", "hash-table"], "Easy"),
        ("pair-diff", "Pair With Difference", ["array", "two-pointers"], "Medium"),
        ("course-order", "Course Order", ["graph", "topological-sort"], "Medium"),
        ("island-count", "Island Count", ["graph", "bfs"], "Medium"),
        ("network-delay", "Network Delay", ["graph", "shortest-path"], "Hard"),
        ("coin-ways", "Coin Ways", ["dynamic-programming"], "Medium"),
        ("edit-steps", "Edit Steps", ["dynamic-programming", "string"], "Hard"),
        ("valid-brackets", "Valid Brackets", ["stack", "string"], "Easy"),
    ]
]
SOLVED = {"two-sum", "valid-brackets", "coin-ways"}


class FixtureAdapter:
    name = PLATFORM
    hosts: tuple[str, ...] = ("practice.invalid",)

    async def describe(self) -> PlatformInfo:
        return PlatformInfo(
            name=self.name,
            tags=sorted({t for p in PROBLEMS for t in p.tags}),
            levels=["Easy", "Medium", "Hard"],
        )

    async def profile(self, handle: str) -> Profile:
        if handle != HANDLE:
            raise UserNotFoundError(f"{PLATFORM} user '{handle}' not found")
        solved = [p for p in PROBLEMS if p.problem_id in SOLVED]
        by_tag: dict[str, int] = {}
        for problem in solved:
            for tag in problem.tags:
                by_tag[tag] = by_tag.get(tag, 0) + 1
        return Profile(
            platform=self.name,
            handle=handle,
            level_summary={"Easy": 2, "Medium": 1, "Hard": 0},
            solved_by_tag=by_tag,
            unsolved_attempts_by_tag={"graph": 3},
            solved_ids=sorted(SOLVED),
        )

    async def search(self, tags: list[str], level: str | None, limit: int) -> list[Problem]:
        found = [
            p for p in PROBLEMS if set(tags) <= set(p.tags) and (level is None or p.level == level)
        ]
        return found[:limit]

    async def problem(self, problem_id: str) -> Problem:
        for problem in PROBLEMS:
            if problem.problem_id == problem_id:
                return problem
        raise ProblemNotFoundError(f"{PLATFORM} problem '{problem_id}' not found")


class Clock:
    def __init__(self) -> None:
        self.at = START

    def __call__(self) -> datetime:
        return self.at


def build_server(db: Path) -> tuple[MCPServer, Clock]:
    clock = Clock()
    server = create_server({PLATFORM: FixtureAdapter()}, ReviewStore(db), now=clock, fuzz=False)
    return server, clock


async def seed_history(server: MCPServer, clock: Clock) -> None:
    """A few weeks of reviews with a recurring mistake, so revisions are due and the
    journal already has labels to reuse."""

    history = [
        ("course-order", "again", [("missed cycle detection", "no visited set on back edges")]),
        ("island-count", "hard", [("missed edge case", "empty grid crashed")]),
        ("course-order", "hard", [("missed cycle detection", "again no cycle check")]),
        ("valid-brackets", "good", [("missed edge case", "empty string")]),
    ]
    for problem_id, rating, mistakes in history:
        await server.call_tool(
            "log_review",
            {
                "platform": PLATFORM,
                "problem_id": problem_id,
                "rating": rating,
                "mistakes": [{"kind": k, "note": n} for k, n in mistakes],
            },
        )
        clock.at += timedelta(days=3)
    clock.at += timedelta(days=14)
