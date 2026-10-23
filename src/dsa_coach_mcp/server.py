"""MCP tools. They return platform data and schedules; judging what is weak or what
to practise next is left to the model that calls them."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field, StringConstraints

from . import srs
from .models import PlatformInfo, Problem, Profile, ReviewCard
from .platforms import PlatformAdapter, PlatformError
from .store import ReviewStore

_INSTRUCTIONS = """\
Coach DSA practice from the user's own history on competitive-programming platforms.
Call list_platforms first to learn each platform's tags and levels, get_profile to see
where the user stands, and search_problems with filters you chose from that data.
After the user solves or revisits a problem, record how well they recalled it with
log_review; revisions_due lists what to revise today."""

_NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_READ_REMOTE = ToolAnnotations(read_only_hint=True, open_world_hint=True)
_READ_LOCAL = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITE_LOCAL = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)


@asynccontextmanager
async def _platform_errors(platform: str) -> AsyncIterator[None]:
    """Turn a platform's own failures into errors the model is shown, not crashes."""

    try:
        yield
    except PlatformError as exc:
        raise ToolError(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise ToolError(f"{platform} is unreachable right now: {exc}") from exc


def create_server(
    adapters: Mapping[str, PlatformAdapter],
    store: ReviewStore,
    today: Callable[[], date] = date.today,
) -> MCPServer:
    server = MCPServer(name="dsa-coach", instructions=_INSTRUCTIONS)
    # Read, reschedule and write one card at a time, so overlapping reviews never
    # both start from the same previous schedule.
    review_lock = asyncio.Lock()

    def adapter_for(platform: str) -> PlatformAdapter:
        adapter = adapters.get(platform)
        if adapter is None:
            raise ToolError(f"Unknown platform '{platform}'. Known: {sorted(adapters)}")
        return adapter

    @server.tool(annotations=_READ_REMOTE)
    async def list_platforms() -> list[PlatformInfo]:
        """Connected platforms, with the tags and levels each one accepts as filters."""

        async with _platform_errors("a platform"):
            return list(await asyncio.gather(*(a.describe() for a in adapters.values())))

    @server.tool(annotations=_READ_REMOTE)
    async def get_profile(
        platform: str,
        handle: str,
        recent_submissions: Annotated[int, Field(ge=0, le=500)] = 20,
    ) -> Profile:
        """The user's standing on one platform: level, solved and unsolved counts per tag,
        and their most recent submissions."""

        async with _platform_errors(platform):
            profile = await adapter_for(platform).profile(handle)
        recent = sorted(profile.submissions, key=lambda s: s.submitted_at, reverse=True)
        return profile.model_copy(update={"submissions": recent[:recent_submissions]})

    @server.tool(annotations=_READ_REMOTE)
    async def search_problems(
        platform: str,
        tags: list[str] | None = None,
        level: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 10,
        exclude_solved_by: str | None = None,
    ) -> list[Problem]:
        """Problems having every tag given, at the level given. Tags and levels must be
        values from list_platforms. With exclude_solved_by, skips that handle's solved
        problems."""

        adapter = adapter_for(platform)
        async with _platform_errors(platform):
            info = await adapter.describe()
            unknown = sorted(set(tags or []) - set(info.tags))
            if unknown:
                raise ToolError(f"Unknown {platform} tags {unknown}; see list_platforms")
            if level is not None and level not in info.levels:
                raise ToolError(f"Unknown {platform} level '{level}'; see list_platforms")

            solved: set[str] = set()
            if exclude_solved_by:
                solved = set((await adapter.profile(exclude_solved_by)).solved_ids)
            # Over-fetch so excluding solved problems can still fill the page.
            found = await adapter.search(tags or [], level, limit + len(solved))
        return [p for p in found if p.problem_id not in solved][:limit]

    @server.tool(annotations=_WRITE_LOCAL)
    async def log_review(
        platform: str,
        problem_id: _NonBlank,
        title: _NonBlank,
        url: AnyHttpUrl,
        quality: Annotated[int, Field(ge=srs.MIN_QUALITY, le=srs.MAX_QUALITY)],
    ) -> ReviewCard:
        """Record how well the user recalled a problem (0 = could not, 5 = instantly) and
        schedule the next revision."""

        adapter_for(platform)
        async with review_lock:
            previous = await asyncio.to_thread(store.get, platform, problem_id)
            schedule = srs.review(
                srs.Schedule(
                    previous.ease, previous.interval_days, previous.repetitions, previous.due
                )
                if previous
                else None,
                quality,
                today(),
            )
            card = ReviewCard(
                platform=platform,
                problem_id=problem_id,
                title=title,
                url=str(url),
                ease=schedule.ease,
                interval_days=schedule.interval_days,
                repetitions=schedule.repetitions,
                due=schedule.due,
            )
            await asyncio.to_thread(store.save, card)
        return card

    @server.tool(annotations=_READ_LOCAL)
    async def revisions_due(
        limit: Annotated[int, Field(ge=1, le=100)] = 10,
    ) -> list[ReviewCard]:
        """Problems due for revision today or overdue, oldest first."""

        return await asyncio.to_thread(store.due, today(), limit)

    return server
