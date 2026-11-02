"""MCP tools. They return platform data and schedules; judging what is weak or what
to practise next is left to the model that calls them."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import scheduling
from .models import (
    Mistake,
    MistakeEntry,
    MistakeKind,
    MistakePatterns,
    NonBlank,
    PlatformInfo,
    Problem,
    Profile,
    ReviewCard,
    ScheduleInfo,
)
from .platforms import PlatformAdapter, PlatformError
from .scheduling import ReviewRating
from .store import CardRecord, ReviewStore

_INSTRUCTIONS = """\
Coach DSA practice from the user's own history on competitive-programming platforms.
Call list_platforms first to learn each platform's tags and levels, get_profile to see
where the user stands, and search_problems with filters you chose from that data.
After the user solves or revisits a problem, record how well they recalled it with
log_review (again, hard, good or easy), together with every mistake they made: label
each mistake with a short kind, reusing a label from mistake_kinds whenever one fits.
revisions_due lists what to revise now, least likely to be remembered first;
mistake_patterns and list_mistakes show where the user keeps going wrong."""

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
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    fuzz: bool = True,
) -> MCPServer:
    server = MCPServer(name="dsa-coach", instructions=_INSTRUCTIONS)
    # Read, reschedule and write one card at a time, so overlapping reviews never
    # both start from the same previous schedule.
    review_lock = asyncio.Lock()

    def lookback(days: int | None) -> date | None:
        """The earliest date ``days`` back from today, or None for all time."""

        if not days:
            return None
        today = now().date()
        return today - timedelta(days=min(days, (today - date.min).days))

    async def scheduler() -> scheduling.Scheduler:
        """Built once per request: the parameters live in SQLite, read off the loop."""

        parameters = await asyncio.to_thread(store.parameters)
        return scheduling.make_scheduler(parameters, fuzz=fuzz)

    def to_card(record: CardRecord, at: datetime, fsrs: scheduling.Scheduler) -> ReviewCard:
        card = record.card
        reviewed = card.last_review is not None
        return ReviewCard(
            platform=record.platform,
            problem_id=record.problem_id,
            title=record.title,
            url=record.url,
            due=card.due,
            stability=card.stability,
            difficulty=card.difficulty,
            retrievability=fsrs.get_card_retrievability(card, at) if reviewed else None,
            reviews=record.reviews,
        )

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
        """Problems having every tag given, at the level given. Take tags and levels from
        list_platforms or from problems the platform returned. With exclude_solved_by,
        skips that handle's solved problems."""

        adapter = adapter_for(platform)
        async with _platform_errors(platform):
            info = await adapter.describe()
            if level is not None and level not in info.levels:
                raise ToolError(f"Unknown {platform} level '{level}'; see list_platforms")

            solved: set[str] = set()
            if exclude_solved_by:
                solved = set((await adapter.profile(exclude_solved_by)).solved_ids)
            # Over-fetch so excluding solved problems can still fill the page.
            found = await adapter.search(tags or [], level, limit + len(solved))
        results = [p for p in found if p.problem_id not in solved][:limit]
        # Platforms' own tag lists are incomplete, so an unlisted tag is only reported
        # when it may be why nothing matched.
        unlisted = sorted(set(tags or []) - set(info.tags))
        if not results and unlisted:
            raise ToolError(
                f"No {platform} problems found; tags {unlisted} are not in its tag list "
                "(see list_platforms)"
            )
        return results

    @server.tool(annotations=_WRITE_LOCAL)
    async def log_review(
        platform: str,
        problem_id: NonBlank,
        rating: ReviewRating,
        mistakes: list[Mistake] | None = None,
    ) -> ReviewCard:
        """Record how well the user recalled a problem, schedule the next revision with
        FSRS, and journal any mistakes made on the way.

        rating: again (could not solve it), hard (solved with real difficulty), good
        (solved after some thought) or easy (solved at once).

        The problem's title, link and tags are read from the platform itself. Give each
        mistake a short kind, reusing an existing one from mistake_kinds when it fits, and
        a note on what went wrong in the user's own words."""

        adapter = adapter_for(platform)
        async with _platform_errors(platform):
            problem = await adapter.problem(problem_id)
        async with review_lock:
            at = now()
            previous = await asyncio.to_thread(store.get, platform, problem.problem_id)
            card = previous.card if previous else scheduling.Card()
            fsrs = await scheduler()
            card, _ = scheduling.review(fsrs, card, rating, at)
            await asyncio.to_thread(
                store.record_review,
                problem,
                card,
                scheduling.to_rating(rating),
                at,
                mistakes or [],
            )
            record = await asyncio.to_thread(store.get, platform, problem.problem_id)
        assert record is not None
        return to_card(record, at, fsrs)

    @server.tool(annotations=_READ_LOCAL)
    async def revisions_due(
        limit: Annotated[int, Field(ge=1, le=100)] = 10,
    ) -> list[ReviewCard]:
        """Problems due for revision now, the one the user is least likely to recall
        first."""

        at = now()
        fsrs = await scheduler()
        records = await asyncio.to_thread(store.due, at)
        cards = [to_card(record, at, fsrs) for record in records]
        ranked = sorted(cards, key=lambda c: (c.retrievability is not None, c.retrievability))
        return ranked[:limit]

    @server.tool(annotations=_READ_LOCAL)
    async def schedule_info() -> ScheduleInfo:
        """The FSRS parameters in use, whether they were fitted to this user's own
        reviews, and how many reviews are logged."""

        parameters = await asyncio.to_thread(store.parameters)
        logs = await asyncio.to_thread(store.review_logs)
        return ScheduleInfo(
            personalised=parameters is not None,
            reviews=len(logs),
            parameters=list((await scheduler()).parameters),
        )

    @server.tool(annotations=_WRITE_LOCAL)
    async def personalize_schedule() -> ScheduleInfo:
        """Fit the FSRS parameters to this user's own review history, so revisions are
        timed to how fast they personally forget. Needs the optimizer extra."""

        logs = await asyncio.to_thread(store.review_logs)
        try:
            parameters = await asyncio.to_thread(scheduling.optimize, logs)
        except RuntimeError as exc:
            raise ToolError(str(exc)) from exc
        if scheduling.is_default(parameters):
            raise ToolError(
                f"FSRS kept its default parameters: {len(logs)} reviews are too few to fit "
                "this user yet. Keep reviewing and try again later."
            )
        await asyncio.to_thread(store.save_parameters, parameters)
        return ScheduleInfo(personalised=True, reviews=len(logs), parameters=parameters)

    @server.tool(annotations=_READ_LOCAL)
    async def mistake_kinds() -> list[MistakeKind]:
        """Every mistake label used so far, most frequent first. Reuse these labels when
        logging new mistakes so the same kind of mistake is counted together."""

        return await asyncio.to_thread(store.mistake_kinds)

    @server.tool(annotations=_READ_LOCAL)
    async def list_mistakes(
        kind: str | None = None,
        tag: str | None = None,
        platform: str | None = None,
        problem_id: str | None = None,
        days: Annotated[int | None, Field(ge=1)] = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
    ) -> list[MistakeEntry]:
        """Journaled mistakes, newest first, with the problem each was made on. Filter by
        label, problem tag, platform, one problem (platform and problem_id), or the last
        ``days`` days."""

        since = lookback(days)
        return await asyncio.to_thread(
            lambda: store.mistakes(
                kind=kind,
                tag=tag,
                platform=platform,
                problem_id=problem_id,
                since=since,
                limit=limit,
            )
        )

    @server.tool(annotations=_READ_LOCAL)
    async def mistake_patterns(
        days: Annotated[int | None, Field(ge=1)] = None,
    ) -> MistakePatterns:
        """Mistake counts per label, broken down by problem tag, platform and month.
        Counts only; reading what they say about the user is up to you."""

        return await asyncio.to_thread(store.patterns, lookback(days))

    @server.prompt()
    def practice_plan(focus: str = "") -> str:
        """Plan the next practice session from the user's own mistakes and progress."""

        target = f" Focus on: {focus}." if focus else ""
        return (
            "Plan my next DSA practice session from my own data."
            f"{target} Read mistake_patterns and list_mistakes to find the mistakes I keep "
            "repeating, and get_profile for where I stand on each platform I use. Then "
            "pick problems with search_problems, using tags and levels from "
            "list_platforms or from my problems, that make me face those same mistakes "
            "again. For each "
            "problem, say which past mistake it targets and what to watch for."
        )

    @server.prompt()
    def revision_quiz() -> str:
        """Quiz the user on today's revisions using the mistakes they made before."""

        return (
            "Quiz me on today's revisions. Call revisions_due, and for each problem call "
            "list_mistakes with its platform and problem_id to see what I got wrong on it "
            "before. Ask me one question at a "
            "time about how I would approach it and what I must not miss this time, "
            "built from those past mistakes, without giving the answer. After I reply, "
            "rate my recall as again, hard, good or easy, then record it with log_review, "
            "including any "
            "new mistake."
        )

    return server
