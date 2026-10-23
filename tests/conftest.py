from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

Handler = Callable[[httpx.Request], Any]


def mock_client(handler: Handler) -> httpx.AsyncClient:
    """An AsyncClient whose every request is answered by ``handler`` as JSON."""

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=handler(request))

    return httpx.AsyncClient(transport=httpx.MockTransport(respond))


def graphql_body(request: httpx.Request) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(request.content)
    return body
