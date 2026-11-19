from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Problem(BaseModel):
    platform: str
    problem_id: str
    title: str
    url: str
    tags: list[str] = Field(default_factory=list)
    # The platform's own grade for it ("Medium", "1400"); each platform grades differently.
    level: str | None = None
    # "platform" when read from the platform's API; "reported" when an MCP client
    # recorded it from a page it read, for platforms with no adapter.
    source: str = "platform"


class Submission(BaseModel):
    problem: Problem
    accepted: bool
    submitted_at: datetime
    # False while the judge has not given a verdict yet, so it is neither a pass nor a fail.
    judged: bool = True


class Profile(BaseModel):
    platform: str
    handle: str
    # The platform's own measures of where the user stands, named as the platform names them.
    level_summary: dict[str, int] = Field(default_factory=dict)
    solved_by_tag: dict[str, int] = Field(default_factory=dict)
    # Problems tried but never accepted, per tag, where the platform exposes full history.
    unsolved_attempts_by_tag: dict[str, int] = Field(default_factory=dict)
    solved_ids: list[str] = Field(default_factory=list)
    submissions: list[Submission] = Field(default_factory=list)
    # Whether rejected submissions are listed too, or only accepted ones.
    rejections_public: bool = False
    # What this platform's data cannot tell you, so the reader does not over-trust it.
    limitations: list[str] = Field(default_factory=list)


class PlatformInfo(BaseModel):
    name: str
    # Filter values exactly as the platform's API accepts them.
    tags: list[str]
    levels: list[str]
    limitations: list[str] = Field(default_factory=list)
    source: str = "platform"


class ReviewCard(BaseModel):
    platform: str
    problem_id: str
    title: str
    url: str
    due: datetime
    # FSRS memory state: days until recall drops to 90%, and how hard the problem is
    # for this user (1-10). Unset until the first review.
    stability: float | None = None
    difficulty: float | None = None
    # FSRS's estimate of the chance the user recalls it right now.
    retrievability: float | None = None
    reviews: int = 0


class PlatformProgress(BaseModel):
    platform: str
    source: str
    problems: int
    reviews: int
    due_now: int


class TagCount(BaseModel):
    tag: str
    count: int


class AccountStats(BaseModel):
    """Where the user stands on a platform they linked, read live from its API."""

    platform: str
    handle: str
    # Accepted problems per level as the platform reports them (LeetCode: All, Easy,
    # Medium, Hard), or its own measures (Codeforces: rating, maxRating).
    levels: dict[str, int] = Field(default_factory=dict)
    # Tags with the most solved problems.
    strongest: list[TagCount] = Field(default_factory=list)
    # Tags with problems tried but never accepted, most first; only where the platform
    # lists failed attempts.
    struggling: list[TagCount] = Field(default_factory=list)
    # Solved tags with the fewest problems: the user has touched them, but barely.
    least_practised: list[TagCount] = Field(default_factory=list)
    # Every solved count per tag, as the platform names its tags.
    solved_by_tag: dict[str, int] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    # Set instead of the stats when the platform could not be read.
    error: str | None = None


class ScheduleInfo(BaseModel):
    personalised: bool
    reviews: int
    parameters: list[float]


class Mistake(BaseModel):
    # The model's own short label for the kind of mistake, reused across reviews so
    # patterns emerge; there is deliberately no fixed list of kinds.
    kind: NonBlank
    # What went wrong, in the user's words.
    note: NonBlank


class MistakeEntry(BaseModel):
    platform: str
    problem_id: str
    title: str
    url: str
    tags: list[str]
    kind: str
    note: str
    logged_on: date


class MistakeKind(BaseModel):
    kind: str
    count: int
    last_seen: date


class MistakeCount(BaseModel):
    kind: str
    # The tag, platform or month the count is broken down by.
    key: str
    count: int


class MistakePatterns(BaseModel):
    kinds: list[MistakeKind]
    by_tag: list[MistakeCount]
    by_platform: list[MistakeCount]
    by_month: list[MistakeCount]


class ReviewEvidence(BaseModel):
    platform: str
    problem_id: str
    # Submissions to this problem since the card was last reviewed (all, if never).
    since: datetime | None
    submissions: int
    accepted: bool
    # Rejected submissions before the first accepted one; None where the platform does not
    # list rejections.
    rejected_before_accepted: int | None
    first_submitted_at: datetime | None
    accepted_at: datetime | None
    suggested_rating: str | None
    reason: str


class ImportResult(BaseModel):
    platform: str
    handle: str
    # Problems added, each with its first accepted submission as its first review.
    imported: int
    # Accepted problems skipped because they are already tracked here.
    already_tracked: int
    # Accepted problems left for a later call, beyond the limit.
    remaining: int
    # Revisions due now, across every platform, after the import.
    due_now: int
    # What the platform's data cannot tell, so the import may be partial.
    limitations: list[str] = Field(default_factory=list)


class TopicForecast(BaseModel):
    tag: str
    problems: int
    # Mean FSRS recall over the tag's reviewed problems, now and after the horizon if
    # none of them is reviewed in between.
    recall_now: float
    recall_later: float


class MistakeRecovery(BaseModel):
    kind: str
    times: int
    last_seen: date
    # Reviews of problems where this mistake happened, logged after it was last seen.
    clean_reviews_since: int


class OverconfidentReview(BaseModel):
    platform: str
    problem_id: str
    title: str
    url: str
    rated_easy_at: datetime
    forgot_at: datetime


class CalibrationBin(BaseModel):
    # Predicted recall in [low, high).
    low: float
    high: float
    reviews: int
    predicted: float
    recalled: float


class Insights(BaseModel):
    horizon_days: int
    forecast: list[TopicForecast]
    recovery: list[MistakeRecovery]
    overconfidence: list[OverconfidentReview]
    calibration: list[CalibrationBin]


class SkillTag(BaseModel):
    """What the user still knows of a topic, not just what they once solved."""

    tag: str
    # Solved on the linked accounts; None when no linked account reports this tag.
    solved: int | None
    # Problems with this tag reviewed in dsa-coach, so FSRS knows their memory.
    reviewed: int
    # Mean FSRS recall of those problems now, and how many of them that adds up to:
    # the number the user would expect to get right today.
    recall: float
    remembered: float


class SkillMap(BaseModel):
    tags: list[SkillTag] = Field(default_factory=list)
    # Tags solved most on the linked accounts but never reviewed here, so their
    # memory is unknown.
    unreviewed: list[TagCount] = Field(default_factory=list)


class ChecklistItem(BaseModel):
    kind: str
    times: int
    last_seen: date
    # The latest note logged with this mistake on this tag, in the user's words.
    note: str


class TagChecklist(BaseModel):
    """The mistakes to check for before submitting a problem with this tag."""

    tag: str
    items: list[ChecklistItem]


class NextStep(BaseModel):
    # revise, mistake, topic or recheck.
    kind: str
    title: str
    detail: str
    url: str | None = None


class Dashboard(BaseModel):
    progress: list[PlatformProgress]
    due: list[ReviewCard]
    patterns: MistakePatterns
    insights: Insights
    # Live stats for each platform the user linked with link_account.
    accounts: list[AccountStats] = Field(default_factory=list)
    # What to do next, picked from the data above by fixed rules.
    next_steps: list[NextStep] = Field(default_factory=list)
    skills: SkillMap = Field(default_factory=SkillMap)
    checklists: list[TagChecklist] = Field(default_factory=list)
