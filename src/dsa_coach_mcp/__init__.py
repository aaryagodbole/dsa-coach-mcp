"""DSA coach MCP server."""

from __future__ import annotations

import argparse
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


async def _dashboard_page() -> str:
    from .browser import dashboard_page

    # The dashboard reads only the local store, so no request goes out on this client.
    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}) as client:
        store = await asyncio.to_thread(ReviewStore, default_db_path())
        return await dashboard_page(create_server(build_adapters(client), store))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="dsa-coach-mcp",
        description="DSA coach MCP server. With no command, serves MCP over stdio.",
    )
    commands = parser.add_subparsers(dest="command")
    dashboard = commands.add_parser(
        "dashboard", help="open the dashboard in a web browser, from your local history"
    )
    dashboard.add_argument("--port", type=int, default=0, help="localhost port (default: any)")
    dashboard.add_argument(
        "--no-open", action="store_true", help="print the address instead of opening it"
    )
    args = parser.parse_args(argv)

    if args.command == "dashboard":
        from .browser import serve

        serve(asyncio.run(_dashboard_page()), args.port, open_browser=not args.no_open)
    else:
        asyncio.run(_serve())
