from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dsa_coach_mcp.evidence import review_evidence
from dsa_coach_mcp.models import Problem, ReviewEvidence, Submission

AT = datetime(2026, 2, 1, tzinfo=UTC)


def submission(problem_id: str, accepted: bool, hours: int) -> Submission:
    problem = Problem(platform="judge", problem_id=problem_id, title=problem_id, url="u")
    return Submission(problem=problem, accepted=accepted, submitted_at=AT + timedelta(hours=hours))


def suggest(
    submissions: list[Submission], since: datetime | None = None, public: bool = True
) -> ReviewEvidence:
    return review_evidence("judge", "a", submissions, since, public)


def test_first_submission_accepted_suggests_good() -> None:
    e = suggest([submission("a", True, 1), submission("b", False, 0)])
    assert (e.suggested_rating, e.submissions, e.rejected_before_accepted) == ("good", 1, 0)
    assert e.accepted_at == AT + timedelta(hours=1)


def test_rejections_before_the_accept_suggest_hard() -> None:
    e = suggest([submission("a", True, 3), submission("a", False, 1), submission("a", False, 2)])
    assert (e.suggested_rating, e.rejected_before_accepted) == ("hard", 2)
    assert e.first_submitted_at == AT + timedelta(hours=1)
    assert e.reason == "Accepted after 2 rejected submissions."


def test_never_accepted_suggests_again() -> None:
    e = suggest([submission("a", False, 1), submission("a", False, 2)])
    assert (e.suggested_rating, e.accepted, e.rejected_before_accepted) == ("again", False, 2)


def test_only_submissions_since_the_last_review_count() -> None:
    old_fail = submission("a", False, 1)
    new_accept = submission("a", True, 5)

    e = suggest([old_fail, new_accept], since=AT + timedelta(hours=2))

    assert (e.suggested_rating, e.submissions) == ("good", 1)


def test_nothing_submitted_suggests_nothing() -> None:
    e = suggest([submission("b", True, 1)])
    assert (e.suggested_rating, e.submissions, e.accepted) == (None, 0, False)
    assert e.rejected_before_accepted is None


def test_hidden_rejections_leave_the_rating_to_the_user() -> None:
    accepted = suggest([submission("a", True, 1)], public=False)
    failed = suggest([submission("a", False, 1)], public=False)

    assert accepted.accepted
    assert accepted.suggested_rating is None
    assert accepted.rejected_before_accepted is None
    assert "ask the user" in accepted.reason
    assert failed.suggested_rating is None


def test_easy_is_never_suggested() -> None:
    for subs in ([submission("a", True, 1)], [submission("a", False, 1), submission("a", True, 2)]):
        assert suggest(subs).suggested_rating != "easy"
