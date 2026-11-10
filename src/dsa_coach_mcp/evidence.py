"""A review rating read from the user's submissions instead of their own estimate.

Self-rated reviews drift towards optimism, and FSRS schedules only as well as its
ratings. A platform's submission history says what happened: whether the problem was
solved, and after how many rejected tries. Speed is not in that history, so evidence
never suggests easy."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from .models import ReviewEvidence, Submission
from .scheduling import ReviewRating


def review_evidence(
    platform: str,
    problem_id: str,
    submissions: Sequence[Submission],
    since: datetime | None,
    rejections_public: bool,
) -> ReviewEvidence:
    attempts = sorted(
        (
            s
            for s in submissions
            if s.problem.problem_id == problem_id and (since is None or s.submitted_at > since)
        ),
        key=lambda s: s.submitted_at,
    )
    first_accepted = next((i for i, s in enumerate(attempts) if s.accepted), None)
    deciding = attempts[:first_accepted] if first_accepted is not None else attempts
    rejected = len(deciding)

    rating: ReviewRating | None
    if not attempts:
        rating, reason = None, "No submissions to this problem since the last review."
    elif any(not s.judged for s in deciding):
        rating = None
        reason = "A submission is still being judged, so the outcome is not known yet."
    elif first_accepted is None:
        rating = ReviewRating("again") if rejections_public else None
        reason = (
            f"{rejected} submissions, none accepted."
            if rejections_public
            else "No accepted submission, and this platform does not list rejected ones."
        )
    elif not rejections_public:
        rating = None
        reason = (
            "Accepted, but this platform does not list rejected submissions, so the "
            "number of tries is unknown: ask the user."
        )
    elif rejected == 0:
        rating, reason = ReviewRating("good"), "Accepted on the first submission."
    else:
        rating = ReviewRating("hard")
        reason = f"Accepted after {rejected} rejected submission{'s' if rejected > 1 else ''}."

    return ReviewEvidence(
        platform=platform,
        problem_id=problem_id,
        since=since,
        submissions=len(attempts),
        accepted=first_accepted is not None,
        rejected_before_accepted=(
            rejected if rejections_public and attempts and all(s.judged for s in deciding) else None
        ),
        first_submitted_at=attempts[0].submitted_at if attempts else None,
        accepted_at=attempts[first_accepted].submitted_at if first_accepted is not None else None,
        suggested_rating=rating.value if rating is not None else None,
        reason=reason,
    )
