"""The chat completions backend's wire format, against a scripted HTTP server."""

from __future__ import annotations

import json
from typing import Any

import httpx

from evals.backends import ChatCompletionsBackend, ToolOutcome, ToolSpec

TOOLS = [ToolSpec("revisions_due", "What to revise.", {"type": "object", "properties": {}})]


def server(replies: list[dict[str, Any]], seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=replies.pop(0))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def reply(message: dict[str, Any], usage: dict[str, int] | None = None) -> dict[str, Any]:
    return {"choices": [{"message": message}], **({"usage": usage} if usage else {})}


async def test_a_tool_call_round_trips_in_the_standard_shape() -> None:
    seen: list[httpx.Request] = []
    http = server(
        [
            reply(
                {
                    "role": "assistant",
                    "content": None,
                    "reasoning": "x",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "revisions_due", "arguments": "{}"},
                        }
                    ],
                },
                {"prompt_tokens": 40, "completion_tokens": 4},
            ),
            reply({"role": "assistant", "content": "Done."}),
        ],
        seen,
    )
    conversation = ChatCompletionsBackend(http, "https://llm.invalid/v1/", "m", "key").start(
        "system", "prompt", TOOLS
    )

    first = await conversation.next_turn()
    conversation.add_tool_results([ToolOutcome(first.tool_requests[0], "nothing due", False)])
    second = await conversation.next_turn()

    assert [(r.id, r.name, r.arguments) for r in first.tool_requests] == [
        ("c1", "revisions_due", {})
    ]
    assert (first.usage.input, first.usage.output, second.text) == (40, 4, "Done.")
    assert str(seen[0].url) == "https://llm.invalid/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer key"
    body = json.loads(seen[0].content)
    assert body["tools"][0] == {
        "type": "function",
        "function": {
            "name": "revisions_due",
            "description": "What to revise.",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    sent = json.loads(seen[1].content)["messages"]
    assert "reasoning" not in sent[-2]
    assert sent[-1] == {"role": "tool", "tool_call_id": "c1", "content": "nothing due"}


async def test_no_key_means_no_auth_header() -> None:
    seen: list[httpx.Request] = []
    backend = ChatCompletionsBackend(
        server([reply({"role": "assistant", "content": "Hi"})], seen), "http://localhost:1/v1", "m"
    )

    await backend.start("s", "p", TOOLS).next_turn()

    assert "authorization" not in seen[0].headers


async def test_arguments_as_objects_bad_json_or_non_objects() -> None:
    calls = [
        {"id": "a", "function": {"name": "t", "arguments": {"k": 1}}},
        {"id": "b", "function": {"name": "t", "arguments": "{nope"}},
        {"id": "c", "function": {"name": "t", "arguments": "[1]"}},
    ]
    backend = ChatCompletionsBackend(
        server([reply({"role": "assistant", "content": "", "tool_calls": calls})], []),
        "http://x/v1",
        "m",
    )

    turn = await backend.start("s", "p", TOOLS).next_turn()

    assert [(r.arguments, r.error is None) for r in turn.tool_requests] == [
        ({"k": 1}, True),
        ({}, False),
        ({}, False),
    ]
