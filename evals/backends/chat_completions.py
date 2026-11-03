"""A backend for the chat completions wire format, which most model APIs speak, hosted
or served locally. The endpoint, key and model are configuration; nothing here names a
provider."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx

from evals.backends.base import ToolOutcome, ToolRequest, ToolSpec, Turn, Usage


class ChatCompletionsBackend:
    name = "chat-completions"

    def __init__(
        self, http: httpx.AsyncClient, base_url: str, model: str, api_key: str | None = None
    ) -> None:
        self._http = http
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        # Servers that need no key, such as a model served on this machine, get no header.
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def start(
        self, system: str, prompt: str, tools: Sequence[ToolSpec]
    ) -> ChatCompletionsConversation:
        return ChatCompletionsConversation(self, system, prompt, tools)


class ChatCompletionsConversation:
    def __init__(
        self, backend: ChatCompletionsBackend, system: str, prompt: str, tools: Sequence[ToolSpec]
    ) -> None:
        self._backend = backend
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        self._tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    async def next_turn(self) -> Turn:
        b = self._backend
        response = await b._http.post(
            b._url,
            headers=b._headers,
            json={"model": b._model, "messages": self._messages, "tools": self._tools},
        )
        response.raise_for_status()
        body = response.json()
        message = body["choices"][0]["message"]
        raw_calls = message.get("tool_calls") or []

        # Echo back only the standard fields: servers add their own (reasoning,
        # annotations) that other servers reject in a request.
        echoed: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
        if raw_calls:
            echoed["tool_calls"] = raw_calls
        self._messages.append(echoed)

        usage = body.get("usage") or {}
        return Turn(
            text=message.get("content") or "",
            tool_requests=[_to_request(call) for call in raw_calls],
            usage=Usage(
                input=usage.get("prompt_tokens", 0), output=usage.get("completion_tokens", 0)
            ),
        )

    def add_tool_results(self, outcomes: Sequence[ToolOutcome]) -> None:
        self._messages.extend(
            {"role": "tool", "tool_call_id": o.request.id, "content": o.text} for o in outcomes
        )


def _to_request(call: dict[str, Any]) -> ToolRequest:
    function = call["function"]
    raw = function.get("arguments") or "{}"
    # The format sends arguments as a JSON string; some servers send an object instead.
    if isinstance(raw, dict):
        return ToolRequest(call["id"], function["name"], raw)
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError:
        return ToolRequest(call["id"], function["name"], {}, error="Arguments were not valid JSON.")
    if not isinstance(arguments, dict):
        return ToolRequest(call["id"], function["name"], {}, error="Arguments were not an object.")
    return ToolRequest(call["id"], function["name"], arguments)
