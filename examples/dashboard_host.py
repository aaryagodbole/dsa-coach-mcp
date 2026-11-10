"""Preview the MCP Apps dashboard without an MCP host.

Seeds a throwaway database through the real server, then writes an HTML page that plays
the host's side of the MCP Apps protocol: it loads the dashboard resource into a
sandboxed iframe, answers ui/initialize, and sends the show_dashboard result as
ui/notifications/tool-result. Open the page in a browser, or screenshot it:

    uv run python examples/dashboard_host.py --out docs/dashboard-preview.html --theme dark

With --demo it adds a note that the data is made up; the Pages workflow publishes that
page as the live demo.
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp import Client

from dsa_coach_mcp.browser import host_page
from dsa_coach_mcp.models import PlatformInfo, Problem, Profile
from dsa_coach_mcp.platforms import ProblemNotFoundError
from dsa_coach_mcp.server import DASHBOARD_URI, create_server
from dsa_coach_mcp.store import ReviewStore

# Sample history so every panel has something to draw. The problems are generic
# exercises on a placeholder judge, not problems from a real one.
SAMPLE = [
    (
        "shortest-path-in-a-grid",
        ["graph", "bfs"],
        ["again", "hard"],
        [("missed cycle detection", "no visited set on the back edge")],
    ),
    (
        "cycle-in-a-directed-graph",
        ["graph", "dfs"],
        ["hard"],
        [
            ("missed cycle detection", "forgot the recursion stack"),
            ("recursion depth", "DFS would overflow on 10^5 nodes"),
        ],
    ),
    (
        "longest-increasing-subsequence",
        ["dynamic-programming"],
        ["good", "good"],
        [("off by one", "dp table sized n instead of n + 1")],
    ),
    ("pair-with-target-sum", ["array", "two-pointers"], ["easy", "again", "good"], []),
    ("longest-palindromic-substring", ["string"], ["hard"], [("missed edge case", "empty string")]),
]


class SampleAdapter:
    name = "sample"
    hosts: tuple[str, ...] = ("sample.invalid",)

    async def describe(self) -> PlatformInfo:
        return PlatformInfo(name=self.name, tags=[], levels=[])

    async def profile(self, handle: str) -> Profile:
        # Placeholder stats for the linked-account panel, counted per level as LeetCode does.
        return Profile(
            platform=self.name,
            handle=handle,
            level_summary={"All": 214, "Easy": 96, "Medium": 101, "Hard": 17},
            solved_by_tag={
                "array": 120,
                "string": 64,
                "hash-table": 58,
                "dynamic-programming": 31,
                "tree": 29,
                "graph": 14,
                "greedy": 22,
                "binary-search": 18,
                "trie": 3,
                "segment-tree": 1,
            },
        )

    async def search(self, tags: list[str], level: str | None, limit: int) -> list[Problem]:
        return []

    async def problem(self, problem_id: str) -> Problem:
        for pid, tags, _, _ in SAMPLE:
            if pid == problem_id:
                return Problem(
                    platform=self.name,
                    problem_id=pid,
                    title=pid.replace("-", " ").capitalize(),
                    url=f"https://sample.invalid/{pid}",
                    tags=tags,
                )
        raise ProblemNotFoundError(problem_id)


class SampleRatedAdapter(SampleAdapter):
    """A second placeholder judge that rates users and lists failed attempts, as
    Codeforces does."""

    name = "sample-rated"

    async def profile(self, handle: str) -> Profile:
        return Profile(
            platform=self.name,
            handle=handle,
            level_summary={"rating": 1432, "maxRating": 1519},
            solved_by_tag={
                "implementation": 88,
                "math": 61,
                "greedy": 57,
                "brute force": 33,
                "constructive algorithms": 21,
                "dp": 9,
                "graphs": 6,
                "dsu": 2,
            },
            unsolved_attempts_by_tag={"dp": 7, "graphs": 4, "math": 3, "binary search": 2},
            rejections_public=True,
        )


async def dashboard_result(db: Path) -> dict[str, Any]:
    clock = {"at": datetime(2026, 1, 1, tzinfo=UTC)}
    server = create_server(
        {"sample": SampleAdapter(), "sample-rated": SampleRatedAdapter()},
        ReviewStore(db),
        now=lambda: clock["at"],
        fuzz=False,
    )
    async with Client(server) as client:
        for platform in ("sample", "sample-rated"):
            await client.call_tool("link_account", {"platform": platform, "handle": "you"})
        for pid, _, ratings, mistakes in SAMPLE:
            for index, rating in enumerate(ratings):
                # Mistakes come with the first attempt, so later reviews show recovery.
                await client.call_tool(
                    "log_review",
                    {
                        "platform": "sample",
                        "problem_id": pid,
                        "rating": rating,
                        "mistakes": [] if index else [{"kind": k, "note": n} for k, n in mistakes],
                    },
                )
                clock["at"] += timedelta(days=1)
        clock["at"] += timedelta(days=20)
        result = await client.call_tool("show_dashboard", {})
        view = await client.read_resource(DASHBOARD_URI)
    return {"structuredContent": result.structured_content, "view": view.contents[0].text}  # type: ignore[union-attr]


DEMO_NOTE = (
    # The note can wrap on a phone, so the view takes whatever height is left.
    "<style>body{display:flex;flex-direction:column;height:100vh}"
    "iframe{flex:1;height:auto!important}</style>"
    '<p style="margin:0;padding:8px 16px;font:600 13px/1.4 system-ui,sans-serif;'
    'text-align:center;background:#2c1810;color:#f5e6d3">'
    "Live demo with made-up sample data. Get your own: "
    '<a style="color:#f08a5d" href="https://github.com/aaryagodbole/dsa-coach-mcp">'
    "github.com/aaryagodbole/dsa-coach-mcp</a></p>"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, default=Path("dashboard-preview.html"))
    parser.add_argument(
        "--theme",
        choices=["light", "dark", "auto"],
        default="light",
        help="auto follows the viewer's browser",
    )
    parser.add_argument("--demo", action="store_true", help="say the data is made up")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        data = asyncio.run(dashboard_result(Path(tmp) / "coach.db"))
    theme = None if args.theme == "auto" else args.theme
    page = host_page(data["structuredContent"], data["view"], theme)
    if args.demo:
        page = page.replace("<body>", "<body>" + DEMO_NOTE, 1)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page, encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
