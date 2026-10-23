from __future__ import annotations

from typing import Any

import httpx
import pytest

from dsa_coach_mcp.platforms import PlatformError, UserNotFoundError
from dsa_coach_mcp.platforms.codeforces import CodeforcesAdapter

from .conftest import mock_client


def problem(contest: int, index: str, tags: list[str], rating: int | None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "contestId": contest,
        "index": index,
        "name": f"P{contest}{index}",
        "tags": tags,
    }
    if rating is not None:
        row["rating"] = rating
    return row


PROBLEMSET = [
    problem(1, "A", ["dp"], 800),
    problem(1, "B", ["dp", "graphs"], 1600),
    problem(2, "A", ["graphs"], None),
]

STATUS = [
    {"problem": problem(1, "A", ["dp"], 800), "verdict": "WRONG_ANSWER", "creationTimeSeconds": 1},
    {"problem": problem(1, "A", ["dp"], 800), "verdict": "OK", "creationTimeSeconds": 2},
    {
        "problem": problem(1, "B", ["dp", "graphs"], 1600),
        "verdict": "TIME_LIMIT_EXCEEDED",
        "creationTimeSeconds": 3,
    },
]


def adapter(results: dict[str, Any]) -> CodeforcesAdapter:
    def handler(request: httpx.Request) -> dict[str, Any]:
        method = request.url.path.rsplit("/", 1)[-1]
        result = results[method]
        if isinstance(result, str):
            return {"status": "FAILED", "comment": result}
        return {"status": "OK", "result": result}

    return CodeforcesAdapter(mock_client(handler))


async def test_describe_collects_tags_and_ratings_from_the_problemset() -> None:
    info = await adapter({"problemset.problems": {"problems": PROBLEMSET}}).describe()

    assert info.tags == ["dp", "graphs"]
    assert info.levels == ["800", "1600"]


async def test_profile_splits_solved_from_attempted_once_per_problem() -> None:
    cf = adapter({"user.info": [{"handle": "bob", "rating": 1500}], "user.status": STATUS})

    profile = await cf.profile("bob")

    assert profile.level_summary == {"rating": 1500}
    assert profile.solved_ids == ["1A"]
    assert profile.solved_by_tag == {"dp": 1}
    assert profile.unsolved_attempts_by_tag == {"dp": 1, "graphs": 1}


async def test_unrated_user_has_no_level() -> None:
    cf = adapter({"user.info": [{"handle": "new"}], "user.status": []})

    assert (await cf.profile("new")).level_summary == {}


async def test_unknown_handle_raises_not_found() -> None:
    cf = adapter({"user.info": "handles: User with handle x not found"})

    with pytest.raises(UserNotFoundError):
        await cf.profile("x")


async def test_other_failures_raise_platform_error() -> None:
    cf = adapter({"problemset.problems": "Call limit exceeded"})

    with pytest.raises(PlatformError, match="Call limit"):
        await cf.describe()


async def test_search_needs_every_tag_and_the_exact_level() -> None:
    cf = adapter({"problemset.problems": {"problems": PROBLEMSET}})

    assert [p.problem_id for p in await cf.search(["graphs"], None, 10)] == ["1B", "2A"]
    assert [p.problem_id for p in await cf.search(["dp", "graphs"], "1600", 10)] == ["1B"]
    assert await cf.search(["graphs"], "800", 10) == []


async def test_a_body_that_is_not_an_object_is_a_platform_error() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    )

    with pytest.raises(PlatformError, match="unexpected response"):
        await CodeforcesAdapter(client).describe()
