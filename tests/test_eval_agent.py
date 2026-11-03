"""The shared eval loop, with a scripted backend: tool requests reach the real MCP
server, outcomes go back to the backend, usage adds up. Backend-independent."""

from __future__ import annotations

from collections.abc import Sequence

from evals.agent import run_task
from evals.backends import ToolOutcome, ToolRequest, ToolSpec, Turn, Usage


class ScriptedBackend:
    name = "scripted"

    def __init__(self, turns: list[Turn]) -> None:
        self.turns = turns
        self.results: list[list[ToolOutcome]] = []
        self.tools: list[ToolSpec] = []
        self.system = ""

    def start(self, system: str, prompt: str, tools: Sequence[ToolSpec]) -> ScriptedBackend:
        self.system, self.tools = system, list(tools)
        return self

    async def next_turn(self) -> Turn:
        return self.turns.pop(0)

    def add_tool_results(self, outcomes: Sequence[ToolOutcome]) -> None:
        self.results.append(list(outcomes))


def turn(*requests: ToolRequest, text: str = "") -> Turn:
    return Turn(text=text, tool_requests=list(requests), usage=Usage(input=10, output=2))


async def test_requests_run_on_the_server_and_outcomes_flow_back() -> None:
    backend = ScriptedBackend(
        [
            turn(ToolRequest("t1", "revisions_due", {})),
            turn(text="Revise course-order first."),
        ]
    )

    calls, usage, final = await run_task(
        backend, {"id": "x", "prompt": "What should I revise?", "seed": "history"}
    )

    assert [(c.name, c.is_error) for c in calls] == [("revisions_due", False)]
    assert final == "Revise course-order first."
    assert (usage.input, usage.output) == (20, 4)
    (outcome,) = backend.results[0]
    assert outcome.request.id == "t1"
    assert "course-order" in outcome.text
    assert "revisions_due" in {t.name for t in backend.tools}
    assert backend.system


async def test_failing_and_unreadable_requests_are_errored_calls() -> None:
    backend = ScriptedBackend(
        [
            turn(
                ToolRequest(
                    "t1",
                    "log_review",
                    {"platform": "practice", "problem_id": "nope", "rating": "good"},
                ),
                ToolRequest("t2", "revisions_due", {}, error="Arguments were not valid JSON."),
            ),
            turn(text="Sorry."),
        ]
    )

    calls, _, _ = await run_task(backend, {"id": "x", "prompt": "log nope"})

    assert [c.is_error for c in calls] == [True, True]
    assert backend.results[0][1].text == "Arguments were not valid JSON."


async def test_a_refusal_ends_the_task() -> None:
    backend = ScriptedBackend([Turn(text="", refused=True)])

    calls, _, final = await run_task(backend, {"id": "x", "prompt": "p"})

    assert (calls, final) == ([], "[refused]")
