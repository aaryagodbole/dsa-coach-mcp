"""The eval loop's plumbing, with a scripted stand-in for the Claude API: tool calls
reach the real MCP server, results go back as tool_result blocks, usage adds up."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from evals.run import run_task


def block(kind: str, **fields: Any) -> SimpleNamespace:
    return SimpleNamespace(type=kind, **fields)


def message(stop_reason: str, *content: SimpleNamespace) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=10,
        cache_read_input_tokens=80,
        cache_creation_input_tokens=0,
    )
    return SimpleNamespace(stop_reason=stop_reason, content=list(content), usage=usage)


class ScriptedClaude:
    def __init__(self, replies: list[SimpleNamespace]) -> None:
        self.replies = replies
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    async def create(self, **request: Any) -> SimpleNamespace:
        self.requests.append(request)
        return self.replies.pop(0)


async def test_tool_calls_run_on_the_server_and_results_flow_back() -> None:
    claude = ScriptedClaude(
        [
            message("tool_use", block("tool_use", id="t1", name="revisions_due", input={})),
            message("end_turn", block("text", text="Revise course-order first.")),
        ]
    )

    calls, usage, final = await run_task(
        claude,
        {"id": "x", "prompt": "What should I revise?", "seed": "history"},  # type: ignore[arg-type]
        "claude-opus-5-5",
        "medium",
    )

    assert [c.name for c in calls] == ["revisions_due"]
    assert not calls[0].is_error
    assert final == "Revise course-order first."
    assert usage == {"input": 200, "output": 20, "cache_read": 160, "cache_write": 0}
    # The loop keeps one messages list, so the final assistant turn now follows the results.
    result = claude.requests[1]["messages"][-2]["content"][0]
    assert (result["type"], result["tool_use_id"]) == ("tool_result", "t1")
    assert "course-order" in result["content"]
    assert claude.requests[0]["tools"][-1]["cache_control"] == {"type": "ephemeral"}


async def test_a_failing_tool_call_is_reported_as_an_error_result() -> None:
    claude = ScriptedClaude(
        [
            message(
                "tool_use",
                block(
                    "tool_use",
                    id="t1",
                    name="log_review",
                    input={"platform": "practice", "problem_id": "nope", "rating": "good"},
                ),
            ),
            message("end_turn", block("text", text="That problem does not exist.")),
        ]
    )

    calls, _, _ = await run_task(
        claude,
        {"id": "x", "prompt": "log nope"},
        "claude-opus-5-5",
        "medium",  # type: ignore[arg-type]
    )

    assert calls[0].is_error
    assert claude.requests[1]["messages"][-2]["content"][0]["is_error"] is True
