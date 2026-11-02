"""Run the agent evals: Claude drives the real MCP server over the MCP protocol, against
the fixture world, and every trajectory is graded deterministically.

This calls the Claude API and costs money. Run it deliberately:

    uv run --group evals python -m evals.run --model claude-opus-5-5 --effort medium
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal, cast

import anthropic
from anthropic.types.beta import (
    BetaMessageParam,
    BetaTextBlockParam,
    BetaToolParam,
    BetaToolResultBlockParam,
)
from mcp import Client

from evals.fixture import build_server, seed_history
from evals.graders import Grade, ToolCall, grade, summarise

TASKS = Path(__file__).with_name("tasks.json")
MAX_TURNS = 12
Effort = Literal["low", "medium", "high", "xhigh", "max"]


def to_claude_tools(mcp_tools: list[Any]) -> list[BetaToolParam]:
    tools: list[BetaToolParam] = [
        {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
        for t in mcp_tools
    ]
    # Tool definitions never change between tasks, so cache them: render order is
    # tools -> system -> messages, and the breakpoint on the last tool covers all of them.
    tools[-1]["cache_control"] = {"type": "ephemeral"}
    return tools


async def run_task(
    claude: anthropic.AsyncAnthropic, task: dict[str, Any], model: str, effort: Effort
) -> tuple[list[ToolCall], dict[str, int], str]:
    with tempfile.TemporaryDirectory() as tmp:
        server, clock = build_server(Path(tmp) / "coach.db")
        if task.get("seed") == "history":
            await seed_history(server, clock)
        async with Client(server) as mcp:
            tools = to_claude_tools((await mcp.list_tools()).tools)
            system: list[BetaTextBlockParam] = [{"type": "text", "text": mcp.instructions or ""}]
            messages: list[BetaMessageParam] = [{"role": "user", "content": task["prompt"]}]
            calls: list[ToolCall] = []
            usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
            final = ""
            for _ in range(MAX_TURNS):
                response = await claude.beta.messages.create(
                    model=model,
                    max_tokens=16000,
                    system=system,
                    tools=tools,
                    messages=messages,
                    output_config={"effort": effort},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
                usage["input"] += response.usage.input_tokens
                usage["output"] += response.usage.output_tokens
                usage["cache_read"] += response.usage.cache_read_input_tokens or 0
                usage["cache_write"] += response.usage.cache_creation_input_tokens or 0
                if response.stop_reason == "refusal":
                    final = "[refused]"
                    break
                messages.append({"role": "assistant", "content": response.content})
                uses = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason != "tool_use" or not uses:
                    final = "".join(b.text for b in response.content if b.type == "text")
                    break
                results: list[BetaToolResultBlockParam] = []
                for use in uses:
                    outcome = await mcp.call_tool(use.name, dict(use.input))
                    text = "".join(c.text for c in outcome.content if c.type == "text")
                    calls.append(ToolCall(use.name, dict(use.input), bool(outcome.is_error)))
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": use.id,
                            "content": text or "(no content)",
                            "is_error": bool(outcome.is_error),
                        }
                    )
                # All results of one turn go back in a single user message.
                messages.append({"role": "user", "content": results})
            return calls, usage, final


async def main_async(args: argparse.Namespace) -> int:
    tasks = json.loads(TASKS.read_text())["tasks"]
    if args.only:
        tasks = [t for t in tasks if t["id"] in args.only]
    claude = anthropic.AsyncAnthropic()
    grades: list[Grade] = []
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    records = []
    for task in tasks:
        calls, usage, final = await run_task(claude, task, args.model, cast(Effort, args.effort))
        result = grade(task, calls)
        grades.append(result)
        for key in totals:
            totals[key] += usage[key]
        mark = "PASS" if result.passed else "FAIL"
        print(f"{mark}  {task['id']:32} calls={len(calls)}  {'; '.join(result.notes)}")
        records.append(
            {
                "grade": asdict(result),
                "calls": [asdict(c) for c in calls],
                "final": final,
                "usage": usage,
            }
        )

    summary = summarise(grades)
    print(
        f"\n{summary.passed}/{summary.tasks} tasks passed · tool selection "
        f"{summary.tool_selection:.0%} · argument accuracy {summary.argument_accuracy:.0%} · "
        f"tool error rate {summary.error_rate:.0%} · {summary.mean_calls:.1f} calls/task"
    )
    print(f"tokens: {totals}")
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "model": args.model,
                    "effort": args.effort,
                    "summary": asdict(summary),
                    "tokens": totals,
                    "tasks": records,
                },
                indent=2,
            )
        )
    return 0 if summary.passed == summary.tasks else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument(
        "--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"]
    )
    parser.add_argument("--only", nargs="*", help="task ids to run")
    parser.add_argument("--out", type=Path, help="write the full results as JSON")
    sys.exit(asyncio.run(main_async(parser.parse_args())))


if __name__ == "__main__":
    main()
