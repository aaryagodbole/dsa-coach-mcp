"""Run the agent evals: a model drives the real MCP server over the MCP protocol, against
the fixture world, and every trajectory is graded deterministically.

The model is configuration, never code: any API that speaks the chat completions format
works, hosted (free tier or paid) or served on this machine.

    EVALS_BASE_URL=<api base url> EVALS_MODEL=<model> EVALS_API_KEY=<key, if needed> \\
        uv run python -m evals.run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from evals.agent import run_task
from evals.backends import BackendError, ChatCompletionsBackend, Usage
from evals.graders import Grade, Summary, grade, summarise

TASKS = Path(__file__).with_name("tasks.json")


def write_results(
    args: argparse.Namespace,
    summary: Summary,
    totals: Usage,
    records: list[dict[str, Any]],
) -> None:
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "base_url": args.base_url,
                    "model": args.model,
                    "summary": asdict(summary),
                    "tokens": asdict(totals),
                    "tasks": records,
                },
                indent=2,
            )
        )


async def main_async(args: argparse.Namespace) -> int:
    tasks = json.loads(TASKS.read_text())["tasks"]
    if args.only:
        tasks = [t for t in tasks if t["id"] in args.only]

    grades: list[Grade] = []
    totals = Usage()
    records: list[dict[str, Any]] = []
    # A model served on this machine can take minutes on a long turn.
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as http:
        try:
            backend = ChatCompletionsBackend(
                http, args.base_url, args.model, os.environ.get(args.api_key_env)
            )
        except BackendError as exc:
            print(exc, file=sys.stderr)
            return 2
        for task in tasks:
            try:
                calls, usage, final = await run_task(backend, task)
            except (httpx.HTTPError, BackendError) as exc:
                print(f"{args.base_url}: {exc}", file=sys.stderr)
                return 2
            result = grade(task, calls)
            grades.append(result)
            totals.add(usage)
            mark = "PASS" if result.passed else "FAIL"
            print(f"{mark}  {task['id']:32} calls={len(calls)}  {'; '.join(result.notes)}")
            records.append(
                {
                    "grade": asdict(result),
                    "calls": [asdict(c) for c in calls],
                    "final": final,
                    "usage": asdict(usage),
                }
            )
            # Written after every task, so a run that dies midway keeps what it paid for.
            await asyncio.to_thread(write_results, args, summarise(grades), totals, records)

    summary = summarise(grades)
    print(
        f"\n{summary.passed}/{summary.tasks} tasks passed · tool selection "
        f"{summary.tool_selection:.0%} · argument accuracy {summary.argument_accuracy:.0%} · "
        f"tool error rate {summary.error_rate:.0%} · {summary.mean_calls:.1f} calls/task"
    )
    print(f"tokens: {asdict(totals)}")
    return 0 if summary.passed == summary.tasks else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EVALS_BASE_URL"),
        help="API base, the part before /chat/completions (or EVALS_BASE_URL)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("EVALS_MODEL"),
        help="model name as the API expects it (or EVALS_MODEL)",
    )
    parser.add_argument(
        "--api-key-env",
        default="EVALS_API_KEY",
        help="environment variable holding the key; unset means no key",
    )
    parser.add_argument("--only", nargs="*", help="task ids to run")
    parser.add_argument("--out", type=Path, help="write the full results as JSON")
    args = parser.parse_args()
    if not args.base_url or not args.model:
        parser.error("set --base-url and --model (or EVALS_BASE_URL and EVALS_MODEL)")
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
