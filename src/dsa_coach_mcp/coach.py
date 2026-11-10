"""What to do next, from the user's own data, by fixed rules.

The dashboard shows these without a model. Each rule picks at most one step, so the
list stays short; the model can still plan in more depth with the prompts."""

from __future__ import annotations

from .models import AccountStats, Insights, NextStep, ReviewCard

# A tag's recall forecast below this is worth a step of its own.
WEAK_RECALL = 0.7


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


def _revise(due: list[ReviewCard]) -> NextStep | None:
    reviewed = [c for c in due if c.retrievability is not None]
    if reviewed:
        card = min(reviewed, key=lambda c: c.retrievability or 0.0)
        return NextStep(
            kind="revise",
            title=f"Revise {card.title}",
            detail=f"{_percent(card.retrievability or 0.0)} chance you still remember it.",
            url=card.url,
        )
    if due:
        card = due[0]
        return NextStep(
            kind="revise",
            title=f"Revise {card.title}",
            detail="Due for its first revision.",
            url=card.url,
        )
    return None


def _mistake(insights: Insights) -> NextStep | None:
    open_ = [m for m in insights.recovery if m.clean_reviews_since == 0]
    if not open_:
        return None
    worst = max(open_, key=lambda m: (m.times, m.last_seen))
    times = "once" if worst.times == 1 else f"{worst.times} times"
    return NextStep(
        kind="mistake",
        title=f"Watch for: {worst.kind}",
        detail=f"Happened {times}, with no clean review of those problems since.",
    )


def _topic(insights: Insights, accounts: list[AccountStats]) -> NextStep | None:
    struggling = [
        (t.count, a.platform, t.tag) for a in accounts if not a.error for t in a.struggling
    ]
    if struggling:
        count, platform, tag = max(struggling, key=lambda s: (s[0], s[2]))
        return NextStep(
            kind="topic",
            title=f"Practise {tag}",
            detail=f"{count} {tag} problems tried and never solved on {platform}.",
        )
    weak = [t for t in insights.forecast if t.recall_later < WEAK_RECALL]
    if weak:
        topic = min(weak, key=lambda t: (t.recall_later, t.tag))
        return NextStep(
            kind="topic",
            title=f"Practise {topic.tag}",
            detail=(
                f"Recall falls to {_percent(topic.recall_later)} in "
                f"{insights.horizon_days} days without revising."
            ),
        )
    return None


def _overconfidence(insights: Insights) -> NextStep | None:
    if not insights.overconfidence:
        return None
    latest = max(insights.overconfidence, key=lambda r: r.forgot_at)
    return NextStep(
        kind="recheck",
        title=f"Re-check {latest.title}",
        detail="You rated it easy, then failed it at the next review.",
        url=latest.url,
    )


def next_steps(
    due: list[ReviewCard], insights: Insights, accounts: list[AccountStats]
) -> list[NextStep]:
    """Up to four steps: the revision most at risk, a mistake that keeps recurring, a
    weak topic, and a problem the user was overconfident about."""

    steps = (
        _revise(due),
        _mistake(insights),
        _topic(insights, accounts),
        _overconfidence(insights),
    )
    return [s for s in steps if s is not None]
