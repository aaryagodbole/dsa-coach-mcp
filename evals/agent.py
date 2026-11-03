"""The eval loop, the same for every backend: build the fixture world, let the model call
the real MCP server's tools until it answers, and record every call for grading."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from mcp import Client

from evals.backends.base import AgentBackend, ToolOutcome, ToolSpec, Usage
from evals.fixture import SEEDS, build_server
from evals.graders import ToolCall

MAX_TURNS = 12


async def run_task(
    backend: AgentBackend, task: dict[str, Any]
) -> tuple[list[ToolCall], Usage, str]:
    with tempfile.TemporaryDirectory() as tmp:
        server, clock = build_server(Path(tmp) / "coach.db")
        if task.get("seed") is not None:
            await SEEDS[task["seed"]](server, clock)
        async with Client(server) as mcp:
            tools = [
                ToolSpec(t.name, t.description or "", t.input_schema)
                for t in (await mcp.list_tools()).tools
            ]
            conversation = backend.start(mcp.instructions or "", task["prompt"], tools)
            calls: list[ToolCall] = []
            usage = Usage()
            for _ in range(MAX_TURNS):
                turn = await conversation.next_turn()
                usage.add(turn.usage)
                if turn.refused:
                    return calls, usage, "[refused]"
                if not turn.tool_requests:
                    return calls, usage, turn.text
                outcomes = []
                for request in turn.tool_requests:
                    if request.error is not None:
                        outcome = ToolOutcome(request, request.error, is_error=True)
                    else:
                        result = await mcp.call_tool(request.name, request.arguments)
                        text = "".join(c.text for c in result.content if c.type == "text")
                        outcome = ToolOutcome(
                            request, text or "(no content)", bool(result.is_error)
                        )
                    calls.append(ToolCall(request.name, request.arguments, outcome.is_error))
                    outcomes.append(outcome)
                conversation.add_tool_results(outcomes)
            return calls, usage, "[turn limit reached]"
