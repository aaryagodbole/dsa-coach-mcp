"""A backend for the chat completions wire format, which most model APIs speak, hosted
or served locally. The endpoint, key and model are configuration; nothing here names a
provider."""

from __future__ import annotations

import asyncio
import ipaddress
import json
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx

from evals.backends.base import BackendError, ToolOutcome, ToolRequest, ToolSpec, Turn, Usage

# Rate limits and overloaded servers clear on their own, and free tiers hit both often;
# without a retry one busy moment ends the whole run.
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
_RETRY_DELAYS = (2.0, 4.0, 8.0, 16.0, 32.0)
_MAX_RETRY_AFTER = 60.0


class ChatCompletionsBackend:
    name = "chat-completions"

    def __init__(
        self, http: httpx.AsyncClient, base_url: str, model: str, api_key: str | None = None
    ) -> None:
        if api_key and not _safe_for_key(base_url):
            raise BackendError(
                f"{base_url} is plain HTTP to another machine; use https so the key is not "
                "sent in the clear"
            )
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
        response = await _post_with_retries(
            b._http,
            b._url,
            b._headers,
            {"model": b._model, "messages": self._messages, "tools": self._tools},
        )
        try:
            body = response.json()
            message = body["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise BackendError(f"{b._url} answered without a chat completions message") from exc
        if not isinstance(message, dict):
            raise BackendError(f"{b._url} answered with a malformed message")
        content, refusal = message.get("content"), message.get("refusal")
        # The format allows only a string or null for both.
        for field, value in (("content", content), ("refusal", refusal)):
            if value is not None and not isinstance(value, str):
                raise BackendError(f"{b._url} answered with a malformed {field}: {value!r}")
        raw_calls = message.get("tool_calls") or []
        requests = [_to_request(call) for call in raw_calls]

        # Echo back only the standard fields: servers add their own (reasoning,
        # annotations) that other servers reject in a request.
        echoed: dict[str, Any] = {"role": "assistant", "content": content or ""}
        if raw_calls:
            echoed["tool_calls"] = raw_calls
        self._messages.append(echoed)

        usage = body.get("usage")
        if usage is None:
            usage = {}
        if not isinstance(usage, dict):
            raise BackendError(f"{b._url} answered with malformed usage: {usage!r}")
        return Turn(
            text=content or "",
            refused=bool(refusal),
            tool_requests=requests,
            usage=Usage(
                input=_token_count(usage, "prompt_tokens"),
                output=_token_count(usage, "completion_tokens"),
            ),
        )

    def add_tool_results(self, outcomes: Sequence[ToolOutcome]) -> None:
        self._messages.extend(
            {"role": "tool", "tool_call_id": o.request.id, "content": o.text} for o in outcomes
        )


async def _post_with_retries(
    http: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any]
) -> httpx.Response:
    for delay in _RETRY_DELAYS:
        try:
            response = await http.post(url, headers=headers, json=body)
        except httpx.TransportError:
            pass
        else:
            if response.status_code not in _TRANSIENT_STATUSES:
                response.raise_for_status()
                return response
            delay = _retry_after(response) or delay
        await asyncio.sleep(delay)
    response = await http.post(url, headers=headers, json=body)
    response.raise_for_status()
    return response


def _retry_after(response: httpx.Response) -> float | None:
    # Only the seconds form; an HTTP date falls back to the default backoff.
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None
    return min(seconds, _MAX_RETRY_AFTER) if seconds > 0 else None


def _token_count(usage: dict[str, Any], key: str) -> int:
    count = usage.get(key)
    if count is None:
        return 0
    # bool is an int subclass, but never a token count.
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise BackendError(f"malformed {key}: {count!r}")
    return count


def _safe_for_key(base_url: str) -> bool:
    parts = urlsplit(base_url)
    if parts.scheme == "https":
        return True
    host = parts.hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _to_request(call: Any) -> ToolRequest:
    # A call without an id or name cannot be answered, so the response itself is broken.
    function = call.get("function") if isinstance(call, dict) else None
    if (
        not isinstance(function, dict)
        or not isinstance(call.get("id"), str)
        or not isinstance(function.get("name"), str)
    ):
        raise BackendError(f"malformed tool call: {call!r}")
    call_id, name = call["id"], function["name"]
    raw = function.get("arguments") or "{}"
    # The format sends arguments as a JSON string; some servers send an object instead.
    if isinstance(raw, dict):
        return ToolRequest(call_id, name, raw)
    if not isinstance(raw, str):
        return ToolRequest(call_id, name, {}, error="Arguments were not valid JSON.")
    try:
        arguments = json.loads(raw)
    except json.JSONDecodeError:
        return ToolRequest(call_id, name, {}, error="Arguments were not valid JSON.")
    if not isinstance(arguments, dict):
        return ToolRequest(call_id, name, {}, error="Arguments were not an object.")
    return ToolRequest(call_id, name, arguments)
