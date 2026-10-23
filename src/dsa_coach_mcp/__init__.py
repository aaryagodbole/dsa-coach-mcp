"""DSA coach MCP server."""

from __future__ import annotations

import asyncio
from importlib.metadata import version

import httpx

from .platforms import build_adapters
from .server import create_server
from .store import ReviewStore, default_db_path

__version__ = version("dsa-coach-mcp")

_USER_AGENT = f"dsa-coach-mcp/{__version__} (+https://github.com/aaryagodbole/dsa-coach-mcp)"


async def _serve() -> None:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0), headers={"User-Agent": _USER_AGENT}
    ) as client:
        store = await asyncio.to_thread(ReviewStore, default_db_path())
        server = create_server(build_adapters(client), store)
        await server.run_stdio_async()


def main() -> None:
    asyncio.run(_serve())
