from __future__ import annotations

from typing import Any

import pytest

from evals.graders import ToolCall, check, grade, summarise

TASK: dict[str, Any] = {
    "id": "t",
    "expect": [
        {"tool": "log_review", "args": {"rating": {"in": ["hard"]}, "mistakes": {"min_items": 1}}}
    ],
    "forbid": ["record_problem"],
    "max_calls": 2,
}


def review(rating: str, mistakes: int = 1, *, is_error: bool = False) -> ToolCall:
    return ToolCall("log_review", {"rating": rating, "mistakes": [{}] * mistakes}, is_error)


@pytest.mark.parametrize(
    ("predicate", "value", "ok"),
    [
        ({"equals": "a"}, "a", True),
        ({"in": ["x", "y"]}, "z", False),
        ({"contains": "Ransom"}, "Hash Tables: ransom note", True),
        ({"min_items": 2}, [1], False),
        ({"has_kind": "missed edge case"}, [{"kind": " Missed Edge Case "}], True),
        ({"no_such_predicate": 1}, 1, False),
    ],
)
def test_predicates(predicate: dict[str, Any], value: Any, ok: bool) -> None:
    assert check(predicate, value) is ok


def test_a_matching_call_passes() -> None:
    assert grade(TASK, [review("hard")]).passed


def test_a_later_corrected_call_still_counts() -> None:
    result = grade(TASK, [review("good"), review("hard")])

    assert result.passed
    assert result.argument_checks_passed == 2


def test_wrong_arguments_fail_but_count_as_selected() -> None:
    result = grade(TASK, [review("easy", mistakes=0)])

    assert not result.passed
    assert (result.tools_selected, result.argument_checks_passed) == (1, 0)
    assert "wrong rating, mistakes" in result.notes[0]


@pytest.mark.parametrize(
    "calls",
    [
        [review("hard"), ToolCall("record_problem", {})],
        [review("hard", is_error=True)],
        [review("hard"), review("hard"), review("hard")],
        [],
    ],
)
def test_forbidden_errored_over_budget_or_missing_calls_fail(calls: list[ToolCall]) -> None:
    assert not grade(TASK, calls).passed


def test_a_wildcard_forbids_any_tool() -> None:
    task = {"id": "chat", "expect": [], "forbid": ["*"], "max_calls": 0}

    assert grade(task, []).passed
    assert not grade(task, [ToolCall("revisions_due", {})]).passed


def test_alternatives_satisfy_an_expectation() -> None:
    task = {"id": "m", "expect": [{"tool": "mistake_patterns", "alternatives": ["list_mistakes"]}]}

    assert grade(task, [ToolCall("list_mistakes", {})]).passed


def test_summary_rates() -> None:
    grades = [grade(TASK, [review("hard")]), grade(TASK, [review("easy")])]

    summary = summarise(grades)

    assert (summary.passed, summary.tool_selection, summary.argument_accuracy) == (1, 1.0, 0.75)
