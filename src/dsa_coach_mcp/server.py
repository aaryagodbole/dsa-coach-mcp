"""MCP tools. They return platform data and schedules; judging what is weak or what
to practise next is left to the model that calls them. The one exception is the
dashboard's short list of next steps, picked by fixed rules (see coach.py) so the view
is useful without a model."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field

from . import coach, evidence, scheduling, skills
from .insights import insights as build_insights
from .models import (
    AccountStats,
    Dashboard,
    ImportResult,
    Mistake,
    MistakeEntry,
    MistakeKind,
    MistakePatterns,
    NonBlank,
    PlatformInfo,
    PlatformProgress,
    Problem,
    Profile,
    ReviewCard,
    ReviewEvidence,
    ScheduleInfo,
    Submission,
    TagCount,
)
from .platforms import PlatformAdapter, PlatformError
from .scheduling import ReviewRating
from .store import CardRecord, ReviewStore

_INSTRUCTIONS = """\
Coach DSA practice from the user's own history on competitive-programming platforms.
Call list_platforms first to learn each platform's tags and levels, get_profile to see
where the user stands, and search_problems with filters you chose from that data.
When the user tells you their username on a platform, save it with link_account; tools
that take a handle then default to it, and the dashboard shows that account's stats.
Then offer import_solved, which schedules revisions for what they already solved there.
After the user solves or revisits a problem, record how well they recalled it with
log_review (again, hard, good or easy). On a platform with an adapter, call
review_evidence with their handle first: it reads the rating from their submissions,
which is more reliable than their own estimate. Log every mistake they made too: label
each mistake with a short kind, reusing a label from mistake_kinds whenever one fits.
revisions_due lists what to revise now, least likely to be remembered first;
mistake_patterns and list_mistakes show where the user keeps going wrong.
For a platform with no adapter, read the problem page (for example with a browser MCP
server) and call record_problem with its URL, title and tags before log_review."""

# MCP Apps (io.modelcontextprotocol/ui, spec 2026-01-26): a tool names a ui:// resource
# that hosts render as an interactive view; other hosts just show the tool's result.
DASHBOARD_URI = "ui://dsa-coach/dashboard"
# How far ahead the dashboard forecasts recall if nothing is revised.
FORECAST_DAYS = 14
MCP_APP_MIME_TYPE = "text/html;profile=mcp-app"
# How long the dashboard waits for each linked platform before showing it as unavailable.
ACCOUNT_TIMEOUT_SECONDS = 10
# Tags listed per account in each of the dashboard's tag lists.
ACCOUNT_TAGS = 5

# Every hint is explicit: unset, destructiveHint defaults to true.
_READ_REMOTE = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)
_READ_LOCAL = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
_WRITE_LOCAL = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)
# Linking replaces the handle saved before, so it overwrites data; it reads the platform
# to check the handle exists.
_LINK_ACCOUNT = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True
)
_UNLINK_ACCOUNT = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
)
# Importing reads the platform and adds cards, but never touches one already tracked, so a
# second call adds nothing new.
_IMPORT = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)
# Problem pages read at once while importing, to fill in tags the profile leaves out.
IMPORT_CONCURRENCY = 4


def account_stats(profile: Profile) -> AccountStats:
    """Summarise a profile for the dashboard: levels and the user's strong and weak tags."""

    def top(counts: Mapping[str, int], reverse: bool) -> list[TagCount]:
        ordered = sorted(counts.items(), key=lambda kv: ((-kv[1] if reverse else kv[1]), kv[0]))
        return [TagCount(tag=tag, count=n) for tag, n in ordered[:ACCOUNT_TAGS] if n > 0]

    solved = profile.solved_by_tag
    strongest = top(solved, reverse=True)
    shown = {t.tag for t in strongest}
    return AccountStats(
        platform=profile.platform,
        handle=profile.handle,
        levels=profile.level_summary,
        strongest=strongest,
        struggling=top(profile.unsolved_attempts_by_tag, reverse=True),
        # Only tags not already listed as strongest, so a short history doesn't repeat them.
        least_practised=top({t: n for t, n in solved.items() if t not in shown}, reverse=False),
        solved_by_tag=solved,
        limitations=profile.limitations,
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

    def adapter_for_host(host: str) -> PlatformAdapter | None:
        return next((a for a in adapters.values() if host in a.hosts), None)

    def adapter_for(platform: str) -> PlatformAdapter:
        adapter = adapters.get(platform)
        if adapter is None:
            raise ToolError(f"Unknown platform '{platform}'. Known: {sorted(adapters)}")
        return adapter

    async def handle_for(platform: str, handle: str | None) -> str:
        """The handle given, else the one the user linked on this platform."""

        if handle and handle.strip():
            return handle.strip()
        linked = dict(await asyncio.to_thread(store.accounts)).get(platform)
        if linked is None:
            raise ToolError(
                f"No handle given and none linked on {platform}. Ask the user for their "
                "username, and save it with link_account."
            )
        return linked

    async def linked_stats(platform: str, handle: str) -> AccountStats:
        """One linked account's stats, or why they could not be read."""

        adapter = adapters.get(platform)
        if adapter is None:
            error = "No adapter for this platform."
            return AccountStats(platform=platform, handle=handle, error=error)
        try:
            async with asyncio.timeout(ACCOUNT_TIMEOUT_SECONDS):
                return account_stats(await adapter.profile(handle))
        except TimeoutError:
            error = f"{platform} did not answer in {ACCOUNT_TIMEOUT_SECONDS} seconds."
        except PlatformError as exc:
            error = str(exc)
        except httpx.HTTPError as exc:
            error = f"{platform} is unreachable right now: {exc}"
        return AccountStats(platform=platform, handle=handle, error=error)

    @server.tool(annotations=_READ_REMOTE)
    async def list_platforms() -> list[PlatformInfo]:
        """Connected platforms, with the tags and levels each one accepts as filters."""

        # Each platform answers on its own: one being down must not hide the others or
        # the platforms recorded locally.
        described = await asyncio.gather(
            *(a.describe() for a in adapters.values()), return_exceptions=True
        )
        infos: list[PlatformInfo] = []
        for adapter, info in zip(adapters.values(), described, strict=True):
            if isinstance(info, PlatformInfo):
                infos.append(info)
            elif isinstance(info, (PlatformError, httpx.HTTPError)):
                infos.append(
                    PlatformInfo(
                        name=adapter.name,
                        tags=[],
                        levels=[],
                        limitations=[f"Unavailable right now: {info}"],
                    )
                )
            else:
                raise info
        reported: dict[str, list[Problem]] = {}
        for problem in await asyncio.to_thread(store.reported_problems):
            reported.setdefault(problem.platform, []).append(problem)
        infos += [
            PlatformInfo(
                name=name,
                tags=sorted({tag for p in problems for tag in p.tags}),
                levels=sorted({p.level for p in problems if p.level}),
                limitations=[
                    "Problems recorded from pages read by the MCP client; not checked "
                    "against the platform, which has no adapter here."
                ],
                source="reported",
            )
            for name, problems in sorted(reported.items())
        ]
        return infos

    @server.tool(annotations=_READ_REMOTE)
    async def get_profile(
        platform: str,
        handle: str | None = None,
        recent_submissions: Annotated[int, Field(ge=0, le=500)] = 20,
    ) -> Profile:
        """The user's standing on one platform: level, solved and unsolved counts per tag,
        and their most recent submissions. Without a handle, uses the one linked with
        link_account."""

        adapter = adapter_for(platform)
        handle = await handle_for(platform, handle)
        async with _platform_errors(platform):
            profile = await adapter.profile(handle)
        recent = sorted(profile.submissions, key=lambda s: s.submitted_at, reverse=True)
        return profile.model_copy(update={"submissions": recent[:recent_submissions]})

    @server.tool(annotations=_READ_REMOTE)
    async def review_evidence(
        platform: str, problem_id: NonBlank, handle: str | None = None
    ) -> ReviewEvidence:
        """Suggest a log_review rating from the user's submissions to this problem since
        it was last reviewed: again if none was accepted, good if the first was, hard if
        rejected ones came first. Never easy, since speed is not in the history. Where the
        platform hides rejected submissions, or nothing was submitted, it suggests
        nothing and says why; ask the user then. Tell the user the suggestion and its
        reason, and let them overrule it. Without a handle, uses the one linked with
        link_account."""

        adapter = adapter_for(platform)
        handle = await handle_for(platform, handle)
        async with _platform_errors(platform):
            # Resolved first, so the id matches the card log_review keeps for it.
            problem = await adapter.problem(problem_id)
            profile = await adapter.profile(handle)
        record = await asyncio.to_thread(store.get, platform, problem.problem_id)
        return evidence.review_evidence(
            platform,
            problem.problem_id,
            profile.submissions,
            record.card.last_review if record else None,
            profile.rejections_public,
        )

    @server.tool(annotations=_LINK_ACCOUNT)
    async def link_account(platform: str, handle: NonBlank) -> AccountStats:
        """Save the user's username on a platform, replacing any saved before, after
        checking it exists. Tools that take a handle default to it, and show_dashboard
        shows this account's stats. Returns those stats."""

        adapter = adapter_for(platform)
        async with _platform_errors(platform):
            profile = await adapter.profile(handle)
        # Saved as the platform spells it, so it matches the platform's own records.
        await asyncio.to_thread(store.link_account, platform, profile.handle, now())
        return account_stats(profile)

    @server.tool(annotations=_UNLINK_ACCOUNT)
    async def unlink_account(platform: str) -> str:
        """Forget the username saved for a platform."""

        if await asyncio.to_thread(store.unlink_account, platform):
            return f"Unlinked {platform}."
        return f"No account was linked on {platform}."

    @server.tool(annotations=_IMPORT)
    async def import_solved(
        platform: str,
        handle: str | None = None,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> ImportResult:
        """Start tracking the problems the user already solved on a platform, most recent
        first, so revisions are scheduled without logging each one. Each problem's first
        accepted submission counts as its first review: good if accepted on the first
        try, hard after rejected tries, and good where the platform hides rejections.
        Problems already tracked are left alone, so calling it again only adds new ones.
        Without a handle, uses the one linked with link_account."""

        adapter = adapter_for(platform)
        handle = await handle_for(platform, handle)
        async with _platform_errors(platform):
            profile = await adapter.profile(handle)

        first_accepted: dict[str, Submission] = {}
        for sub in sorted(profile.submissions, key=lambda s: s.submitted_at):
            if sub.accepted:
                first_accepted.setdefault(sub.problem.problem_id, sub)
        tracked = await asyncio.to_thread(store.tracked, platform)
        new = sorted(
            (s for pid, s in first_accepted.items() if pid not in tracked),
            key=lambda s: s.submitted_at,
            reverse=True,
        )
        chosen, remaining = new[:limit], len(new) - min(len(new), limit)

        gate = asyncio.Semaphore(IMPORT_CONCURRENCY)

        async def with_tags(problem: Problem) -> Problem:
            # Some profiles list problems without tags; the problem page has them. A page
            # that fails to load still leaves the problem worth tracking.
            if problem.tags:
                return problem
            async with gate:
                try:
                    return await adapter.problem(problem.problem_id)
                except (PlatformError, httpx.HTTPError):
                    return problem

        problems = await asyncio.gather(*(with_tags(s.problem) for s in chosen))
        async with review_lock:
            fsrs = await scheduler()
            for sub, problem in zip(chosen, problems, strict=True):
                found = evidence.review_evidence(
                    platform,
                    sub.problem.problem_id,
                    profile.submissions,
                    since=None,
                    rejections_public=profile.rejections_public,
                )
                rating = ReviewRating(found.suggested_rating or "good")
                card, _ = scheduling.review(fsrs, scheduling.Card(), rating, sub.submitted_at)
                await asyncio.to_thread(
                    store.record_review,
                    problem,
                    card,
                    scheduling.to_rating(rating),
                    sub.submitted_at,
                    [],
                )
            due = await asyncio.to_thread(store.due, now())
        return ImportResult(
            platform=platform,
            handle=profile.handle,
            imported=len(chosen),
            already_tracked=len(first_accepted) - len(new),
            remaining=remaining,
            due_now=len(due),
            limitations=profile.limitations,
        )

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

        if platform in adapters:
            async with _platform_errors(platform):
                problem = await adapters[platform].problem(problem_id)
        else:
            reported = await asyncio.to_thread(store.problem, platform, problem_id)
            if reported is None:
                raise ToolError(
                    f"No problem '{problem_id}' recorded for {platform}. Platforms with an "
                    f"adapter: {sorted(adapters)}; for any other, call record_problem with "
                    "the problem's URL first."
                )
            problem = reported
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

    @server.tool(annotations=_WRITE_LOCAL)
    async def record_problem(
        url: AnyHttpUrl,
        title: NonBlank,
        tags: list[NonBlank] | None = None,
        level: NonBlank | None = None,
    ) -> Problem:
        """Record a problem from a platform this server has no adapter for, as read from
        its page: its URL, title, the tags the page shows and its difficulty as the page
        states it. The platform is the URL's host, and the problem id its path. Returns
        the platform and problem_id to pass to log_review."""

        parts = urlsplit(str(url))
        host = (parts.hostname or "").removeprefix("www.")
        adapter = adapter_for_host(host)
        if adapter is not None:
            raise ToolError(
                f"{host} has an adapter: call log_review with platform '{adapter.name}' and "
                "its problem id, so the problem is read from the platform itself."
            )
        problem_id = parts.path.strip("/") + (f"?{parts.query}" if parts.query else "")
        if not problem_id:
            raise ToolError(f"{url} has no path to identify a problem by")
        problem = Problem(
            platform=host,
            problem_id=problem_id,
            title=title,
            url=str(url),
            tags=list(dict.fromkeys(tags or [])),
            level=level,
            source="reported",
        )
        return await asyncio.to_thread(store.save_problem, problem)

    @server.tool(annotations=_READ_LOCAL)
    async def progress() -> list[PlatformProgress]:
        """Per platform the user has reviewed on: problems reviewed, reviews logged, and
        problems due for revision now."""

        rows = await asyncio.to_thread(store.progress, now())
        return [
            PlatformProgress(
                platform=platform,
                source="platform" if platform in adapters else "reported",
                problems=problems,
                reviews=reviews,
                due_now=due_now,
            )
            for platform, problems, reviews, due_now in rows
        ]

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

    @server.resource(
        DASHBOARD_URI,
        name="dashboard",
        title="DSA coach dashboard",
        mime_type=MCP_APP_MIME_TYPE,
        meta={"ui": {"prefersBorder": True}},
    )
    def dashboard_view() -> str:
        """Interactive view for show_dashboard."""

        return files("dsa_coach_mcp").joinpath("ui/dashboard.html").read_text("utf-8")

    @server.tool(annotations=_READ_REMOTE, meta={"ui": {"resourceUri": DASHBOARD_URI}})
    async def show_dashboard(
        limit: Annotated[int, Field(ge=1, le=100)] = 15,
        days: Annotated[int | None, Field(ge=1)] = None,
    ) -> Dashboard:
        """Show the user's progress per platform, the revisions due now ordered by how
        likely they are to be forgotten, a heatmap of mistakes by label and tag, and what
        the history says about their memory: recall per tag now and two weeks out, which
        mistakes stopped recurring, problems rated easy then failed, and how well FSRS's
        predictions matched, plus live stats for each account linked with link_account,
        how many problems per tag the user would still get right today, and their own
        checklist of past mistakes per tag.
        Hosts that support MCP Apps render it as an interactive dashboard."""

        at = now()
        linked = await asyncio.to_thread(store.accounts)
        # Fetched together and each on its own: a slow or broken platform shows as
        # unavailable without holding up or hiding the rest.
        accounts = asyncio.gather(*(linked_stats(p, h) for p, h in linked))
        rows = await asyncio.to_thread(store.progress, at)
        fsrs = await scheduler()
        records = await asyncio.to_thread(store.due, at)
        due = sorted(
            (to_card(record, at, fsrs) for record in records),
            key=lambda c: (c.retrievability is not None, c.retrievability),
        )[:limit]
        dashboard = Dashboard(
            progress=[
                PlatformProgress(
                    platform=platform,
                    source="platform" if platform in adapters else "reported",
                    problems=problems,
                    reviews=reviews,
                    due_now=due_now,
                )
                for platform, problems, reviews, due_now in rows
            ],
            due=due,
            patterns=await asyncio.to_thread(store.patterns, lookback(days)),
            insights=await asyncio.to_thread(
                build_insights,
                await asyncio.to_thread(store.histories),
                fsrs,
                at,
                FORECAST_DAYS,
            ),
            accounts=list(await accounts),
        )
        dashboard.next_steps = coach.next_steps(due, dashboard.insights, dashboard.accounts)
        dashboard.skills = skills.skill_map(dashboard.insights.forecast, dashboard.accounts)
        dashboard.checklists = skills.checklists(await asyncio.to_thread(store.mistakes_by_tag))
        return dashboard

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
    def weekly_report(days: str = "7") -> str:
        """Report on the user's last week of practice and say what to do next."""

        return (
            f"Give me a short coaching report on my last {days} days of DSA practice, "
            "from my own data only. Call show_dashboard for my linked accounts, what is "
            "due and the next steps it suggests; mistake_patterns and list_mistakes with "
            f"days={days} for what went wrong this week; and progress for how much I "
            "reviewed. Then write: what I did, what is slipping (problems and tags I am "
            "forgetting), which mistakes keep coming back, and a plan of three concrete "
            "things to do next, each naming a problem, tag or mistake from that data. If I "
            "have not linked an account, ask for my username and save it with link_account."
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
