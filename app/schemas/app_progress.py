"""The app's progress contract (flueai-app docs/backend-contract.md, routes 3.1, 3.3, 3.4)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SessionKind = Literal["lesson", "checkpoint", "review", "practice", "voice_lesson"]


class Attempt(BaseModel):
    exerciseId: str = Field(min_length=1, max_length=80)
    conceptId: str = Field(min_length=1, max_length=80)
    correct: bool
    usedHint: bool = False


class SessionResultRequest(BaseModel):
    client: Literal["app", "web"] = "app"
    contentVersion: str = Field(min_length=1, max_length=20)
    activityId: str = Field(min_length=1, max_length=64)
    kind: SessionKind
    completedAt: datetime
    origin: Literal["normal", "pre_signup"] = "normal"
    attempts: list[Attempt] = Field(default_factory=list, max_length=100)


class SessionOutcome(BaseModel):
    xpAwarded: int
    firstTryCorrect: int
    mainTotal: int
    passed: bool | None = None
    unlockedActivityId: str | None = None
    newAchievementIds: list[str] = []
    streakIncremented: bool


class AppProfile(BaseModel):
    fullName: str | None = None
    dailyGoalXp: Literal[20, 40, 60] = 20
    motivation: Literal["daily", "travel", "work"] = "daily"


class XpTotals(BaseModel):
    total: int
    today: int


class StreakState(BaseModel):
    current: int
    longest: int
    lastPracticeDay: str | None = None


class AchievementOwned(BaseModel):
    id: str
    unlockedAt: str | None = None


class TrackState(BaseModel):
    completedActivityIds: list[str]
    currentActivityId: str | None = None


class Tracks(BaseModel):
    fundamentals: TrackState


class Summary(BaseModel):
    profile: AppProfile
    xp: XpTotals
    streak: StreakState
    achievements: list[AchievementOwned]
    reviewsDue: int
    tracks: Tracks
    serverDay: str


class SessionResult(BaseModel):
    replayed: bool
    result: SessionOutcome
    summary: Summary


class DueConcept(BaseModel):
    conceptId: str
    dueDay: str
    stage: int
