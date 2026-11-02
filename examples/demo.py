"""Drive dsa-coach-mcp the way an MCP client does and record the session as an SVG.

Launches the real server over stdio against a throwaway database, calls its tools on
live LeetCode and Codeforces data, and saves the transcript to docs/demo.svg:

    uv run python examples/demo.py --leetcode <user> --codeforces <handle>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.terminal_theme import MONOKAI

console = Console(record=True, width=104)


async def call(client: Client, tool: str, **arguments: Any) -> Any:
    console.print(f"\n[bold cyan]→ {tool}[/]([dim]{json.dumps(arguments)[1:-1]}[/])")
    result = await client.call_tool(tool, arguments)
    if result.is_error:
        raise RuntimeError(result.content[0].text)  # type: ignore[union-attr]
    content = result.structured_content or {}
    return content.get("result", content)


async def run(leetcode: str, codeforces: str, db: Path) -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "dsa_coach_mcp"],
        env={**os.environ, "DSA_COACH_DB": str(db)},
    )
    async with Client(server) as client:
        tools = await client.list_tools()
        prompts = await client.list_prompts()
        console.print(
            Panel.fit(
                f"[bold]dsa-coach-mcp[/] · {len(tools.tools)} tools · "
                f"{len(prompts.prompts)} prompts · connected over stdio",
                border_style="green",
            )
        )

        lc = await call(
            client, "get_profile", platform="leetcode", handle=leetcode, recent_submissions=0
        )
        cf = await call(
            client, "get_profile", platform="codeforces", handle=codeforces, recent_submissions=0
        )

        table = Table(title="One profile across platforms", title_style="bold")
        table.add_column("Platform")
        table.add_column("Level")
        table.add_column("Most solved tags")
        table.add_column("Least solved tags")
        for profile in (lc, cf):
            ranked = sorted(profile["solved_by_tag"].items(), key=lambda kv: -kv[1])
            table.add_row(
                f"{profile['platform']} · {profile['handle']}",
                ", ".join(f"{k} {v}" for k, v in profile["level_summary"].items()),
                ", ".join(f"{t} {n}" for t, n in ranked[:3]),
                ", ".join(f"{t} {n}" for t, n in ranked[-3:]),
            )
        console.print(table)

        thin_tag = min(lc["solved_by_tag"].items(), key=lambda kv: kv[1])[0]
        level = sorted(lc["level_summary"].items(), key=lambda kv: -kv[1])[0][0]
        problems = await call(
            client,
            "search_problems",
            platform="leetcode",
            tags=[thin_tag],
            level=level,
            limit=3,
            exclude_solved_by=leetcode,
        )
        for p in problems:
            console.print(f"   [green]●[/] {p['title']} [dim]({p['level']}) {p['url']}[/]")

        problem = problems[0]
        console.print("\n[dim]# The user retries it and the model journals what went wrong:[/]")
        await call(
            client,
            "log_review",
            platform="leetcode",
            problem_id=problem["problem_id"],
            quality=2,
            mistakes=[
                {"kind": "missed edge case", "note": "did not handle the smallest input"},
                {
                    "kind": "brute force first",
                    "note": "simulated every move before looking for the pattern",
                },
            ],
        )
        await call(
            client,
            "log_review",
            platform="leetcode",
            problem_id=problem["problem_id"],
            quality=3,
            mistakes=[
                {"kind": "missed edge case", "note": "smallest input wrong again"},
            ],
        )

        patterns = await call(client, "mistake_patterns")
        mistakes = Table(title="Mistake journal", title_style="bold")
        mistakes.add_column("Mistake (model's own label)")
        mistakes.add_column("Times", justify="right")
        mistakes.add_column("On tags")
        for kind in patterns["kinds"]:
            tags = [c["key"] for c in patterns["by_tag"] if c["kind"] == kind["kind"]]
            mistakes.add_row(kind["kind"], str(kind["count"]), ", ".join(tags))
        console.print(mistakes)

        quiz = await client.get_prompt("revision_quiz", {})
        console.print(
            Panel(
                quiz.messages[0].content.text,  # type: ignore[union-attr]
                title="prompt: revision_quiz",
                border_style="magenta",
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--leetcode", required=True, help="LeetCode username")
    parser.add_argument("--codeforces", required=True, help="Codeforces handle")
    parser.add_argument("--out", type=Path, default=Path("docs/demo.svg"))
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(run(args.leetcode, args.codeforces, Path(tmp) / "coach.db"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(args.out), title="dsa-coach-mcp", theme=MONOKAI)
    print(f"saved {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
