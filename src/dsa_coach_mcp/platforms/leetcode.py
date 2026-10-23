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
query search($filters: QuestionListFilterInput, $limit: Int!) {
  questionList(categorySlug: "", limit: $limit, skip: 0, filters: $filters) {
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
        body = response.json()
        data = body.get("data")
        if not isinstance(data, dict):
            raise PlatformError(f"LeetCode returned no data: {body.get('errors')}")
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
        data = await self._query(_SEARCH_QUERY, {"filters": filters, "limit": limit})
        return [
            Problem(
                platform=self.name,
                problem_id=row["titleSlug"],
                title=row["title"],
                url=_problem_url(row["titleSlug"]),
                tags=[tag["slug"] for tag in row["topicTags"]],
                level=row["difficulty"],
            )
            for row in data["questionList"]["data"]
            if not row["isPaidOnly"]
        ]
