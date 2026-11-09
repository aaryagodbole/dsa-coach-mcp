"""Preview the MCP Apps dashboard without an MCP host.

Seeds a throwaway database through the real server, then writes an HTML page that plays
the host's side of the MCP Apps protocol: it loads the dashboard resource into a
sandboxed iframe, answers ui/initialize, and sends the show_dashboard result as
ui/notifications/tool-result. Open the page in a browser, or screenshot it:

    uv run python examples/dashboard_host.py --out docs/dashboard-preview.html --theme dark
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp import Client

from dsa_coach_mcp.models import PlatformInfo, Problem, Profile
from dsa_coach_mcp.platforms import ProblemNotFoundError
from dsa_coach_mcp.server import DASHBOARD_URI, create_server
from dsa_coach_mcp.store import ReviewStore

HOST_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>dashboard preview</title>
<style>body{{margin:0;background:{bg}}} iframe{{border:0;width:100%;height:100vh}}</style>
</head><body><iframe id="view" sandbox="allow-scripts"></iframe>
<script>
const view = document.getElementById("view");
const result = {result};
window.addEventListener("message", (e) => {{
  const m = e.data;
  if (!m || m.jsonrpc !== "2.0") return;
  if (m.method === "ui/initialize") {{
    view.contentWindow.postMessage({{jsonrpc: "2.0", id: m.id, result: {{
      protocolVersion: "2026-01-26", hostInfo: {{name: "preview", version: "1"}},
      hostCapabilities: {{}}, hostContext: {{theme: "{theme}"}}}}}}, "*");
  }} else if (m.method === "ui/open-link") {{
    window.open(m.params.url, "_blank", "noopener");
    view.contentWindow.postMessage({{jsonrpc: "2.0", id: m.id, result: {{}}}}, "*");
  }} else if (m.method === "ui/notifications/initialized") {{
    view.contentWindow.postMessage({{jsonrpc: "2.0",
      method: "ui/notifications/tool-result", params: result}}, "*");
  }}
}});
view.srcdoc = {view};
</script></body></html>
"""

# Sample history so every panel has something to draw. Problem ids and titles are
# placeholders, not real problems.
SAMPLE = [
    (
        "p-graphs-1",
        ["graph", "bfs"],
        ["again", "hard"],
        [("missed cycle detection", "no visited set on the back edge")],
    ),
    (
        "p-graphs-2",
        ["graph", "dfs"],
        ["hard"],
        [
            ("missed cycle detection", "forgot the recursion stack"),
            ("recursion depth", "DFS would overflow on 10^5 nodes"),
        ],
    ),
    (
        "p-dp-1",
        ["dynamic-programming"],
        ["good", "good"],
        [("off by one", "dp table sized n instead of n + 1")],
    ),
    ("p-arrays-1", ["array", "two-pointers"], ["easy", "again", "good"], []),
    ("p-strings-1", ["string"], ["hard"], [("missed edge case", "empty string")]),
]


class SampleAdapter:
    name = "sample"
    hosts: tuple[str, ...] = ("sample.invalid",)

    async def describe(self) -> PlatformInfo:
        return PlatformInfo(name=self.name, tags=[], levels=[])

    async def profile(self, handle: str) -> Profile:
        return Profile(platform=self.name, handle=handle)

    async def search(self, tags: list[str], level: str | None, limit: int) -> list[Problem]:
        return []

    async def problem(self, problem_id: str) -> Problem:
        for pid, tags, _, _ in SAMPLE:
            if pid == problem_id:
                return Problem(
                    platform=self.name,
                    problem_id=pid,
                    title=pid.replace("-", " "),
                    url=f"https://sample.invalid/{pid}",
                    tags=tags,
                )
        raise ProblemNotFoundError(problem_id)


async def dashboard_result(db: Path) -> dict[str, Any]:
    clock = {"at": datetime(2026, 1, 1, tzinfo=UTC)}
    server = create_server(
        {"sample": SampleAdapter()}, ReviewStore(db), now=lambda: clock["at"], fuzz=False
    )
    async with Client(server) as client:
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


def _script_json(value: object) -> str:
    """JSON that is safe inside a <script> element: a literal "</script>" in the
    dashboard's HTML would otherwise end the host page's script early."""

    return json.dumps(value).replace("</", "<\\/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, default=Path("dashboard-preview.html"))
    parser.add_argument("--theme", choices=["light", "dark"], default="light")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        data = asyncio.run(dashboard_result(Path(tmp) / "coach.db"))
    page = HOST_PAGE.format(
        bg="#0d1117" if args.theme == "dark" else "#ffffff",
        theme=args.theme,
        result=_script_json({"structuredContent": data["structuredContent"]}),
        view=_script_json(data["view"]),
    )
    args.out.write_text(page, encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
