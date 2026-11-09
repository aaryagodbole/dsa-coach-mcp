from __future__ import annotations

from typing import Any

import httpx
import pytest

from dsa_coach_mcp.platforms import PlatformError, ProblemNotFoundError, UserNotFoundError
from dsa_coach_mcp.platforms.codeforces import CodeforcesAdapter


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
    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        result = results[method]
        if isinstance(result, tuple):
            status, comment = result
            return httpx.Response(status, json={"status": "FAILED", "comment": comment})
        return httpx.Response(200, json={"status": "OK", "result": result})

    return CodeforcesAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


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


async def test_a_queued_or_judging_submission_is_not_yet_judged() -> None:
    status = [
        {"problem": problem(1, "A", ["dp"], 800), "verdict": "OK", "creationTimeSeconds": 1},
        {"problem": problem(1, "A", ["dp"], 800), "verdict": "TESTING", "creationTimeSeconds": 2},
        {"problem": problem(1, "A", ["dp"], 800), "creationTimeSeconds": 3},
    ]
    cf = adapter({"user.info": [{"handle": "bob"}], "user.status": status})

    profile = await cf.profile("bob")

    assert [s.judged for s in profile.submissions] == [True, False, False]


async def test_unrated_user_has_no_level() -> None:
    cf = adapter({"user.info": [{"handle": "new"}], "user.status": []})

    assert (await cf.profile("new")).level_summary == {}


async def test_unknown_handle_raises_not_found() -> None:
    cf = adapter({"user.info": (400, "handles: User with handle x not found")})

    with pytest.raises(UserNotFoundError):
        await cf.profile("x")


async def test_other_failures_raise_platform_error() -> None:
    cf = adapter({"problemset.problems": (503, "Call limit exceeded")})

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


async def test_problem_is_looked_up_in_the_problemset() -> None:
    cf = adapter({"problemset.problems": {"problems": PROBLEMSET}})

    assert (await cf.problem("1B")).tags == ["dp", "graphs"]
    with pytest.raises(ProblemNotFoundError):
        await cf.problem("9Z")


async def test_a_problem_added_after_the_cache_is_found_on_refetch() -> None:
    added = problem(9, "Z", ["dp"], 1200)
    pages = [{"problems": PROBLEMSET}, {"problems": [*PROBLEMSET, added]}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "OK", "result": pages.pop(0)})

    cf = CodeforcesAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await cf.describe()

    assert (await cf.problem("9Z")).title == "P9Z"


async def test_a_cold_miss_fetches_the_problemset_once() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"status": "OK", "result": {"problems": PROBLEMSET}})

    cf = CodeforcesAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(ProblemNotFoundError):
        await cf.problem("9Z")
    assert calls == 1


async def test_a_failed_refresh_keeps_the_cached_problemset() -> None:
    answers = [
        httpx.Response(200, json={"status": "OK", "result": {"problems": PROBLEMSET}}),
        httpx.Response(503, json={"status": "FAILED", "comment": "Call limit exceeded"}),
    ]
    cf = CodeforcesAdapter(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda request: answers.pop(0)))
    )
    await cf.describe()

    with pytest.raises(PlatformError):
        await cf.problem("9Z")
    assert (await cf.problem("1A")).problem_id == "1A"
