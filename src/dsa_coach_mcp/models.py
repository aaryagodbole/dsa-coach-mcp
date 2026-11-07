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


class Dashboard(BaseModel):
    progress: list[PlatformProgress]
    due: list[ReviewCard]
    patterns: MistakePatterns
    insights: Insights
