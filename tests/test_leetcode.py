from __future__ import annotations

from typing import Any

import httpx
import pytest

from dsa_coach_mcp.platforms import PlatformError, UserNotFoundError
from dsa_coach_mcp.platforms.leetcode import LeetCodeAdapter

from .conftest import graphql_body, mock_client

CATALOG = {
    "allQuestionsCount": [
        {"difficulty": "All", "count": 10},
        {"difficulty": "Easy", "count": 5},
        {"difficulty": "Medium", "count": 3},
        {"difficulty": "Hard", "count": 2},
    ],
    "questionTopicTags": {"edges": [{"node": {"slug": "array"}}, {"node": {"slug": "graph"}}]},
}

USER = {
    "matchedUser": {
        "username": "alice",
        "submitStatsGlobal": {
            "acSubmissionNum": [
                {"difficulty": "All", "count": 0},
                {"difficulty": "Easy", "count": 0},
                {"difficulty": "Medium", "count": 0},
                {"difficulty": "Hard", "count": 0},
            ]
        },
        "tagProblemCounts": {
            "advanced": [{"tagSlug": "graph", "problemsSolved": 1}],
            "intermediate": [],
            "fundamental": [{"tagSlug": "array", "problemsSolved": 4}],
        },
    },
    "recentAcSubmissionList": [
        {"title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1700000000"},
        {"title": "Two Sum", "titleSlug": "two-sum", "timestamp": "1690000000"},
    ],
}


def adapter_answering(answer: dict[str, Any], seen: list[dict[str, Any]]) -> LeetCodeAdapter:
    def handler(request: httpx.Request) -> dict[str, Any]:
        body = graphql_body(request)
        seen.append(body)
        if "allQuestionsCount" in body["query"]:
            return {"data": CATALOG}
        return {"data": answer}

    return LeetCodeAdapter(mock_client(handler))


async def test_describe_reads_levels_from_the_catalog_without_its_total_row() -> None:
    info = await adapter_answering({}, []).describe()

    assert info.levels == ["Easy", "Medium", "Hard"]
    assert info.tags == ["array", "graph"]


async def test_profile_keeps_levels_even_when_every_count_is_zero() -> None:
    profile = await adapter_answering(USER, []).profile("alice")

    assert profile.level_summary == {"Easy": 0, "Medium": 0, "Hard": 0}
    assert profile.solved_by_tag == {"graph": 1, "array": 4}
    assert profile.solved_ids == ["two-sum"]
    assert profile.limitations


def adapter_with_body(body: dict[str, Any]) -> LeetCodeAdapter:
    def handler(request: httpx.Request) -> dict[str, Any]:
        if "allQuestionsCount" in graphql_body(request)["query"]:
            return {"data": CATALOG}
        return body

    return LeetCodeAdapter(mock_client(handler))


async def test_unknown_user_raises_not_found() -> None:
    adapter = adapter_with_body(
        {
            "data": {"matchedUser": None, "recentAcSubmissionList": None},
            "errors": [{"message": "That user does not exist.", "path": ["matchedUser"]}],
        }
    )

    with pytest.raises(UserNotFoundError):
        await adapter.profile("nobody")


async def test_other_graphql_errors_are_platform_errors() -> None:
    adapter = adapter_with_body(
        {"data": {"questionList": None}, "errors": [{"message": "Query unavailable"}]}
    )

    with pytest.raises(PlatformError, match="Query unavailable"):
        await adapter.search([], None, limit=5)


async def test_search_sends_the_enum_spelling_and_drops_paid_problems() -> None:
    seen: list[dict[str, Any]] = []
    rows = [
        {
            "title": "Free",
            "titleSlug": "free",
            "difficulty": "Medium",
            "isPaidOnly": False,
            "topicTags": [{"slug": "graph"}],
        },
        {
            "title": "Paid",
            "titleSlug": "paid",
            "difficulty": "Medium",
            "isPaidOnly": True,
            "topicTags": [{"slug": "graph"}],
        },
    ]
    adapter = adapter_answering({"questionList": {"data": rows}}, seen)

    found = await adapter.search(["graph"], "Medium", limit=5)

    assert [p.problem_id for p in found] == ["free"]
    assert seen[-1]["variables"]["filters"] == {"tags": ["graph"], "difficulty": "MEDIUM"}


async def test_search_pages_past_paid_problems_to_fill_the_limit() -> None:
    def row(slug: str, paid: bool) -> dict[str, Any]:
        return {
            "title": slug,
            "titleSlug": slug,
            "difficulty": "Easy",
            "isPaidOnly": paid,
            "topicTags": [],
        }

    pages = {0: [row("paid-1", True), row("paid-2", True)], 2: [row("free", False)]}
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> dict[str, Any]:
        body = graphql_body(request)
        seen.append(body)
        return {"data": {"questionList": {"data": pages[body["variables"]["skip"]]}}}

    found = await LeetCodeAdapter(mock_client(handler)).search([], None, limit=2)

    assert [p.problem_id for p in found] == ["free"]
    assert [b["variables"]["skip"] for b in seen] == [0, 2]


async def test_a_failed_search_is_a_platform_error_not_a_crash() -> None:
    adapter = adapter_with_body(
        {
            "data": {"questionList": None},
            "errors": [{"message": "Internal error", "path": ["questionList"]}],
        }
    )

    with pytest.raises(PlatformError, match="Internal error"):
        await adapter.search([], None, limit=5)
