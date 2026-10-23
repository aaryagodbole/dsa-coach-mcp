from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from ..models import PlatformInfo, Problem, Profile, Submission
from .base import PlatformError, UserNotFoundError

_GRAPHQL_URL = "https://leetcode.com/graphql"
# LeetCode rejects GraphQL calls without a same-site referer.
_HEADERS = {"Referer": "https://leetcode.com"}
# The most the public recent-submissions query returns; full history needs a login.
_RECENT_LIMIT = 20

_PROFILE_QUERY = """
query profile($username: String!, $limit: Int!) {
  matchedUser(username: $username) {
    username
    submitStatsGlobal { acSubmissionNum { difficulty count } }
    tagProblemCounts {
      advanced { tagSlug problemsSolved }
      intermediate { tagSlug problemsSolved }
      fundamental { tagSlug problemsSolved }
    }
  }
  recentAcSubmissionList(username: $username, limit: $limit) { title titleSlug timestamp }
}
"""

_DESCRIBE_QUERY = """
{
  allQuestionsCount { difficulty count }
  questionTopicTags { edges { node { slug } } }
}
"""

_SEARCH_QUERY = """
query search($filters: QuestionListFilterInput, $limit: Int!, $skip: Int!) {
  questionList(categorySlug: "", limit: $limit, skip: $skip, filters: $filters) {
    data { title titleSlug difficulty isPaidOnly topicTags { slug } }
  }
}
"""


def _problem_url(slug: str) -> str:
    return f"https://leetcode.com/problems/{slug}/"


def _difficulties(rows: list[dict[str, Any]]) -> list[str]:
    """The difficulty names, minus the row that is only the sum of the others.

    Read off the whole catalog's counts, which are never all zero, so the total row
    is the one whose count is half of everything listed."""

    total = sum(int(row["count"]) for row in rows)
    totals = [row for row in rows if int(row["count"]) * 2 == total]
    return [row["difficulty"] for row in rows if not totals or row is not totals[0]]


def _is_null_field_error(error: object, data: dict[str, Any]) -> bool:
    path = error.get("path") if isinstance(error, dict) else None
    return isinstance(path, list) and bool(path) and data.get(path[0]) is None


class LeetCodeAdapter:
    name = "leetcode"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._info: PlatformInfo | None = None

    async def _query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self._client.post(
            _GRAPHQL_URL, json={"query": query, "variables": variables or {}}, headers=_HEADERS
        )
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise PlatformError("LeetCode returned a non-JSON response") from exc
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise PlatformError(f"LeetCode returned no data: {body}")
        # A lookup that finds nothing (an unknown user) comes back as an error on a field
        # that is null; callers check for that null. Any other error is a real failure.
        errors = [e for e in body.get("errors") or [] if not _is_null_field_error(e, data)]
        if errors:
            raise PlatformError(f"LeetCode query failed: {errors}")
        return data

    async def describe(self) -> PlatformInfo:
        if self._info is None:
            data = await self._query(_DESCRIBE_QUERY)
            self._info = PlatformInfo(
                name=self.name,
                tags=[edge["node"]["slug"] for edge in data["questionTopicTags"]["edges"]],
                levels=_difficulties(data["allQuestionsCount"]),
                limitations=["Paid-only problems are never returned by search."],
            )
        return self._info

    async def profile(self, handle: str) -> Profile:
        levels = (await self.describe()).levels
        data = await self._query(_PROFILE_QUERY, {"username": handle, "limit": _RECENT_LIMIT})
        user = data.get("matchedUser")
        if user is None:
            raise UserNotFoundError(f"LeetCode user '{handle}' not found")

        solved_by_tag = {
            row["tagSlug"]: row["problemsSolved"]
            for group in user["tagProblemCounts"].values()
            for row in group
        }
        submissions = [
            Submission(
                problem=Problem(
                    platform=self.name,
                    problem_id=row["titleSlug"],
                    title=row["title"],
                    url=_problem_url(row["titleSlug"]),
                ),
                accepted=True,
                submitted_at=datetime.fromtimestamp(int(row["timestamp"]), tz=UTC),
            )
            for row in data.get("recentAcSubmissionList") or []
        ]
        return Profile(
            platform=self.name,
            handle=user["username"],
            level_summary={
                row["difficulty"]: int(row["count"])
                for row in user["submitStatsGlobal"]["acSubmissionNum"]
                if row["difficulty"] in levels
            },
            solved_by_tag=solved_by_tag,
            solved_ids=list(dict.fromkeys(s.problem.problem_id for s in submissions)),
            submissions=submissions,
            limitations=[
                f"Only the {_RECENT_LIMIT} most recent accepted submissions are public, so "
                "solved_ids is partial and failed attempts are not visible."
            ],
        )

    async def search(self, tags: list[str], level: str | None, limit: int) -> list[Problem]:
        filters: dict[str, Any] = {}
        if tags:
            filters["tags"] = tags
        if level:
            # The filter takes the difficulty as an enum constant, not as it is displayed.
            filters["difficulty"] = level.upper()
        found: list[Problem] = []
        skip = 0
        # Paid-only problems are dropped after the page comes back, so keep paging
        # until the free ones fill the request or the catalog runs out.
        while len(found) < limit:
            data = await self._query(
                _SEARCH_QUERY, {"filters": filters, "limit": limit, "skip": skip}
            )
            rows = data["questionList"]["data"]
            found.extend(
                Problem(
                    platform=self.name,
                    problem_id=row["titleSlug"],
                    title=row["title"],
                    url=_problem_url(row["titleSlug"]),
                    tags=[tag["slug"] for tag in row["topicTags"]],
                    level=row["difficulty"],
                )
                for row in rows
                if not row["isPaidOnly"]
            )
            if len(rows) < limit:
                break
            skip += len(rows)
        return found[:limit]
