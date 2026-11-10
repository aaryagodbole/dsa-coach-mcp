"""What the user still knows per topic, and their own checklist of mistakes per topic."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date

from .models import (
    AccountStats,
    ChecklistItem,
    SkillMap,
    SkillTag,
    TagChecklist,
    TagCount,
    TopicForecast,
)

# Topics shown in each list, and mistakes per topic in a checklist.
TOPICS = 8
CHECKLIST_ITEMS = 5


def tag_key(tag: str) -> str:
    """One spelling for a tag across platforms: "Binary Search" and "binary-search" match."""

    return "-".join(tag.lower().replace("_", " ").split())


def skill_map(forecast: list[TopicForecast], accounts: list[AccountStats]) -> SkillMap:
    """Per reviewed tag: solved on the linked accounts, reviewed here, and how many of
    those reviewed problems the user would get right today; plus the tags solved most
    but never reviewed."""

    solved: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    for account in accounts:
        if account.error:
            continue
        for tag, n in account.solved_by_tag.items():
            solved[tag_key(tag)] += n
            names.setdefault(tag_key(tag), tag)

    reviewed = {tag_key(t.tag): t for t in forecast}
    tags = [
        SkillTag(
            tag=t.tag,
            solved=solved.get(key),
            reviewed=t.problems,
            recall=t.recall_now,
            remembered=t.recall_now * t.problems,
        )
        for key, t in reviewed.items()
    ]
    # The topics with the most behind them first; recall breaks ties, weakest first.
    tags.sort(key=lambda s: (-(s.solved or s.reviewed), s.recall, s.tag))
    unreviewed = sorted(
        ((names[key], n) for key, n in solved.items() if key not in reviewed and n > 0),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return SkillMap(
        tags=tags[:TOPICS],
        unreviewed=[TagCount(tag=tag, count=n) for tag, n in unreviewed[:TOPICS]],
    )


def checklists(rows: Iterable[tuple[str, str, int, date, str]]) -> list[TagChecklist]:
    """The user's mistakes per tag, most frequent first: what to check before
    submitting a problem with that tag. Tags with the most mistakes come first."""

    by_tag: dict[str, list[ChecklistItem]] = defaultdict(list)
    for tag, kind, times, last_seen, note in rows:
        by_tag[tag].append(ChecklistItem(kind=kind, times=times, last_seen=last_seen, note=note))
    ordered = sorted(by_tag.items(), key=lambda kv: (-sum(i.times for i in kv[1]), kv[0]))
    return [
        TagChecklist(
            tag=tag,
            items=sorted(items, key=lambda i: (-i.times, -i.last_seen.toordinal(), i.kind))[
                :CHECKLIST_ITEMS
            ],
        )
        for tag, items in ordered[:TOPICS]
    ]
