from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import httpx

from ..models import PlatformInfo, Problem, Profile, Submission
from .base import PlatformError, UserNotFoundError

_API_URL = "https://codeforces.com/api"
# The user.info fields that describe skill; the rest (avatar, contribution, ...) do not.
_LEVEL_FIELDS = ("rating", "maxRating")


def _problem_id(problem: dict[str, Any]) -> str | None:
    contest = problem.get("contestId")
    return f"{contest}{problem['index']}" if contest is not None else None


def _to_problem(problem: dict[str, Any], problem_id: str) -> Problem:
    rating = problem.get("rating")
    return Problem(
        platform="codeforces",
        problem_id=problem_id,
        title=problem["name"],
        url=f"https://codeforces.com/problemset/problem/{problem['contestId']}/{problem['index']}",
        tags=list(problem.get("tags") or []),
        level=str(rating) if rating is not None else None,
    )


class CodeforcesAdapter:
    name = "codeforces"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._problemset: list[dict[str, Any]] | None = None

    async def _call(self, method: str, params: dict[str, str]) -> Any:
        response = await self._client.get(f"{_API_URL}/{method}", params=params)
        body = response.json()
        if body.get("status") != "OK":
            comment = str(body.get("comment") or response.status_code)
            if "not found" in comment.lower():
                raise UserNotFoundError(comment)
            raise PlatformError(f"Codeforces {method}: {comment}")
        return body["result"]

    async def _all_problems(self) -> list[dict[str, Any]]:
        if self._problemset is None:
            result = await self._call("problemset.problems", {})
            self._problemset = list(result["problems"])
        return self._problemset

    async def describe(self) -> PlatformInfo:
        problems = await self._all_problems()
        tags = sorted({tag for p in problems for tag in p.get("tags") or []})
        ratings = sorted({p["rating"] for p in problems if p.get("rating") is not None})
        return PlatformInfo(
            name=self.name,
            tags=tags,
            levels=[str(r) for r in ratings],
            limitations=["Unrated problems match no level filter."],
        )

    async def profile(self, handle: str) -> Profile:
        info = (await self._call("user.info", {"handles": handle}))[0]
        rows = await self._call("user.status", {"handle": handle})

        submissions: list[Submission] = []
        tags_of: dict[str, list[str]] = {}
        solved: set[str] = set()
        for row in rows:
            problem_id = _problem_id(row["problem"])
            if problem_id is None:
                continue
            accepted = row.get("verdict") == "OK"
            submissions.append(
                Submission(
                    problem=_to_problem(row["problem"], problem_id),
                    accepted=accepted,
                    submitted_at=datetime.fromtimestamp(row["creationTimeSeconds"], tz=UTC),
                )
            )
            tags_of[problem_id] = list(row["problem"].get("tags") or [])
            if accepted:
                solved.add(problem_id)

        solved_by_tag: dict[str, int] = defaultdict(int)
        unsolved_by_tag: dict[str, int] = defaultdict(int)
        for problem_id, tags in tags_of.items():
            bucket = solved_by_tag if problem_id in solved else unsolved_by_tag
            for tag in tags:
                bucket[tag] += 1

        return Profile(
            platform=self.name,
            handle=info["handle"],
            level_summary={f: int(info[f]) for f in _LEVEL_FIELDS if f in info},
            solved_by_tag=dict(solved_by_tag),
            unsolved_attempts_by_tag=dict(unsolved_by_tag),
            solved_ids=sorted(solved),
            submissions=submissions,
        )

    async def search(self, tags: list[str], level: str | None, limit: int) -> list[Problem]:
        wanted = set(tags)
        found: list[Problem] = []
        for problem in await self._all_problems():
            problem_id = _problem_id(problem)
            if problem_id is None or not wanted <= set(problem.get("tags") or []):
                continue
            candidate = _to_problem(problem, problem_id)
            if level is not None and candidate.level != level:
                continue
            found.append(candidate)
            if len(found) >= limit:
                break
        return found
