"""Deterministic graders for agent trajectories: no LLM judges anything here.

A task names the tool calls it expects, with predicates on their arguments; the tools
the agent must not touch; and a budget of calls. A trajectory passes when every
expectation is met by some call, nothing forbidden ran, no call errored, and it stayed
within budget."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]
    is_error: bool = False


@dataclass
class Grade:
    task_id: str
    passed: bool
    expectations_met: int
    expectations_total: int
    # Expectations whose tool was called at all, right arguments or not.
    tools_selected: int
    argument_checks_passed: int
    argument_checks_total: int
    forbidden_calls: list[str] = field(default_factory=list)
    errored_calls: int = 0
    calls: int = 0
    over_budget: bool = False
    notes: list[str] = field(default_factory=list)


PREDICATES: dict[str, Callable[[Any, Any], bool]] = {
    "equals": lambda value, expected: bool(value == expected),
    "in": lambda value, expected: value in expected,
    "contains": lambda value, expected: (
        isinstance(value, str) and expected.lower() in value.lower()
    ),
    "min_items": lambda value, expected: isinstance(value, list) and len(value) >= expected,
    "has_kind": lambda value, expected: (
        isinstance(value, list)
        and any(
            isinstance(item, Mapping)
            and str(item.get("kind", "")).strip().lower() == expected.lower()
            for item in value
        )
    ),
}


def check(predicate: Mapping[str, Any], value: Any) -> bool:
    """One argument predicate. Unknown predicate names fail, so a typo in tasks.json
    cannot quietly pass."""

    ((kind, expected),) = predicate.items()
    test = PREDICATES.get(kind)
    return test is not None and test(value, expected)


def _argument_score(args: Mapping[str, Mapping[str, Any]], call: ToolCall) -> tuple[int, list[str]]:
    failed = [
        name for name, predicate in args.items() if not check(predicate, call.arguments.get(name))
    ]
    return len(args) - len(failed), failed


def grade(task: Mapping[str, Any], calls: Sequence[ToolCall]) -> Grade:
    expectations: list[Mapping[str, Any]] = task.get("expect", [])
    forbid: list[str] = task.get("forbid", [])
    budget: int | None = task.get("max_calls")

    result = Grade(
        task_id=task["id"],
        passed=False,
        expectations_met=0,
        expectations_total=len(expectations),
        tools_selected=0,
        argument_checks_passed=0,
        argument_checks_total=sum(len(e.get("args", {})) for e in expectations),
        calls=len(calls),
    )

    for expectation in expectations:
        names = {expectation["tool"], *expectation.get("alternatives", [])}
        args = expectation.get("args", {})
        candidates = [c for c in calls if c.name in names]
        if not candidates:
            result.notes.append(f"never called {expectation['tool']}")
            continue
        result.tools_selected += 1
        # The best-matching call counts: a later, corrected call can satisfy it.
        best_score, best_failed = max(
            (_argument_score(args, c) for c in candidates), key=lambda scored: scored[0]
        )
        result.argument_checks_passed += best_score
        if not best_failed:
            result.expectations_met += 1
        else:
            result.notes.append(f"{expectation['tool']}: wrong {', '.join(best_failed)}")

    result.forbidden_calls = [c.name for c in calls if "*" in forbid or c.name in forbid]
    result.errored_calls = sum(c.is_error for c in calls)
    result.over_budget = budget is not None and len(calls) > budget
    if result.forbidden_calls:
        result.notes.append(f"forbidden: {', '.join(result.forbidden_calls)}")
    if result.errored_calls:
        result.notes.append(f"{result.errored_calls} tool call(s) errored")
    if result.over_budget:
        result.notes.append(f"{len(calls)} calls, budget {budget}")

    result.passed = (
        result.expectations_met == result.expectations_total
        and not result.forbidden_calls
        and not result.errored_calls
        and not result.over_budget
    )
    return result


@dataclass
class Summary:
    tasks: int
    passed: int
    tool_selection: float
    argument_accuracy: float
    error_rate: float
    mean_calls: float


def summarise(grades: Sequence[Grade]) -> Summary:
    expected = sum(g.expectations_total for g in grades)
    selected = sum(g.tools_selected for g in grades)
    arg_total = sum(g.argument_checks_total for g in grades)
    calls = sum(g.calls for g in grades)
    return Summary(
        tasks=len(grades),
        passed=sum(g.passed for g in grades),
        tool_selection=selected / expected if expected else 1.0,
        argument_accuracy=(
            sum(g.argument_checks_passed for g in grades) / arg_total if arg_total else 1.0
        ),
        error_rate=sum(g.errored_calls for g in grades) / calls if calls else 0.0,
        mean_calls=calls / len(grades) if grades else 0.0,
    )
