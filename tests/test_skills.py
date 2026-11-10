from __future__ import annotations

from datetime import date

import pytest

from dsa_coach_mcp.models import AccountStats, TopicForecast
from dsa_coach_mcp.skills import checklists, skill_map, tag_key


def topic(tag: str, problems: int, recall: float) -> TopicForecast:
    return TopicForecast(tag=tag, problems=problems, recall_now=recall, recall_later=recall)


def account(platform: str, solved: dict[str, int], error: str | None = None) -> AccountStats:
    return AccountStats(platform=platform, handle="a", solved_by_tag=solved, error=error)


@pytest.mark.parametrize(
    "tag", ["binary-search", "Binary Search", "binary_search", "  binary   search "]
)
def test_tag_spellings_match_across_platforms(tag: str) -> None:
    assert tag_key(tag) == "binary-search"


def test_counts_what_is_still_remembered_against_what_was_solved() -> None:
    accounts = [
        account("leetcode", {"graph": 30, "binary-search": 4}),
        account("codeforces", {"graph": 10, "binary search": 2, "dp": 1}),
        account("down", {"graph": 99}, error="unreachable"),
    ]
    forecast = [topic("graph", 10, 0.6), topic("binary-search", 2, 0.9), topic("trie", 1, 0.5)]

    result = skill_map(forecast, accounts)

    rows = {t.tag: t for t in result.tags}
    assert (rows["graph"].solved, rows["graph"].reviewed) == (40, 10)
    assert rows["graph"].remembered == pytest.approx(6.0)
    assert rows["binary-search"].solved == 6
    # Reviewed here but no linked account reports it.
    assert rows["trie"].solved is None
    # Most solved first; an unreported tag ranks by what was reviewed.
    assert [t.tag for t in result.tags] == ["graph", "binary-search", "trie"]
    assert [(t.tag, t.count) for t in result.unreviewed] == [("dp", 1)]


def test_without_linked_accounts_it_still_reports_memory() -> None:
    result = skill_map([topic("graph", 3, 0.5), topic("dp", 3, 0.4)], [])

    assert [(t.tag, t.solved) for t in result.tags] == [("dp", None), ("graph", None)]
    assert result.unreviewed == []


def test_lists_are_capped() -> None:
    forecast = [topic(f"t{i}", 1, 0.5) for i in range(12)]
    solved = {f"u{i}": 12 - i for i in range(12)}

    result = skill_map(forecast, [account("leetcode", solved)])

    assert len(result.tags) == 8
    assert [t.tag for t in result.unreviewed][:2] == ["u0", "u1"]
    assert len(result.unreviewed) == 8


def test_checklists_put_the_most_frequent_mistakes_first() -> None:
    rows = [
        ("graph", "missed cycle", 3, date(2026, 1, 2), "no visited set"),
        ("graph", "recursion depth", 3, date(2026, 1, 5), "overflow on 1e5"),
        ("graph", "off by one", 1, date(2026, 1, 9), "n vs n+1"),
        ("dp", "off by one", 2, date(2026, 1, 3), "table size"),
    ]

    result = checklists(rows)

    assert [c.tag for c in result] == ["graph", "dp"]
    graph = result[0]
    # Ties go to the more recent mistake.
    assert [i.kind for i in graph.items] == ["recursion depth", "missed cycle", "off by one"]
    assert graph.items[0].note == "overflow on 1e5"


def test_checklists_are_capped_per_tag_and_overall() -> None:
    rows = [(f"t{t}", f"k{k}", 1, date(2026, 1, 1), "n") for t in range(10) for k in range(7)]

    result = checklists(rows)

    assert len(result) == 8
    assert all(len(c.items) == 5 for c in result)
