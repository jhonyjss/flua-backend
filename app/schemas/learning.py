"""Schemas for learning endpoints (lesson progress, sessions, XP, streaks)."""
from typing import Any, Literal

from pydantic import BaseModel, Field

LessonStatus = Literal["unlocked", "in_progress", "completed"]


class LessonProgressRow(BaseModel):
    id: str | int | None = None
    lesson_id: str
    status: str
    score: int | None = None
    topics_completed: int = 0
    completed_topic_ids: list[str] = []
    time_spent_seconds: int = 0
    best_rating: int | None = None
    attempts: int = 0
    started_at: str | None = None
    completed_at: str | None = None


class StartLessonRequest(BaseModel):
    sessionId: str


class CompleteLessonRequest(BaseModel):
    topicsCompleted: int = 0
    timeSpentSeconds: int = 0
    rating: int = Field(default=0, ge=0, le=5)
    sessionId: str


class SaveTopicRequest(BaseModel):
    topicId: str


class UnlockLessonRequest(BaseModel):
    unlockedBy: str = "previous_lesson"


class OkResponse(BaseModel):
    success: bool = True


class ClassSessionRequest(BaseModel):
    session_id: str
    lesson_id: str
    level: str = "beginner"
    goals_total: int = 0
    goals_completed: int = 0
    messages_exchanged: int = 0
    corrections_received: int = 0
    elapsed_seconds: int = 0
    rating: int | None = None
    status: str | None = None


class AwardXpRequest(BaseModel):
    amount: int = Field(ge=0, le=10000)


class XpResult(BaseModel):
    newXp: int
    newLevel: int
    leveledUp: bool


class RecordPracticeRequest(BaseModel):
    timeSeconds: int = 0
    lessonCompleted: bool = False


class PracticeResult(BaseModel):
    streak: int
    isNewDay: bool
    achievementsUnlocked: list[str] = []


class InProgressLessons(BaseModel):
    """lessonId → number of completed topics."""
    lessons: dict[str, int]


class TopicIds(BaseModel):
    topicIds: list[str]


class UnlockedLessons(BaseModel):
    lessonIds: list[str]


class AchievementIds(BaseModel):
    achievementIds: list[str]


# ── Vocabulary / grammar (study) ─────────────────────────────────────
class VocabularyWordRequest(BaseModel):
    word: str = Field(min_length=1, max_length=200)
    translation: str = ""
    example: str = ""
    roomId: int | None = None
    source: str = ""


class VocabularySummary(BaseModel):
    total: int = 0
    learning: int = 0
    mastered: int = 0
    dueForReview: int = 0


class SaveResult(BaseModel):
    success: bool
    error: str | None = None
    data: dict[str, Any] | None = None


# ── Per-lesson time budget (server-enforced) ─────────────────────────
class LessonTimeStatus(BaseModel):
    limitSeconds: int
    consumedSeconds: int
    remainingSeconds: int
    expired: bool
    # Admins: no lesson budget (the session mint lets them past it too); clients don't count down.
    isUnlimited: bool = False
    # Subscribers: the month's pool of Flua minutes (voice_minutes). None when it doesn't apply
    # (free trial lessons, admins). remainingSeconds above is already the smaller of the two.
    monthlyLimitSeconds: int | None = None
    monthlyRemainingSeconds: int | None = None
    # Which budget ran out: the lesson's 10 minutes, or the month's minutes.
    expiredReason: Literal["lesson", "month"] | None = None


class HeartbeatRequest(BaseModel):
    deltaSeconds: int = Field(default=0, ge=0, le=600)


class LessonActivity(BaseModel):
    """Seconds spent in one lesson in total (never reset; not the budget)."""
    activeSeconds: int


class VoiceMinutesStatus(BaseModel):
    """The month's pool of Flua voice minutes (60 Starter, 120 Pro). Free accounts: limit 0, never expired."""
    limitSeconds: int
    consumedSeconds: int
    remainingSeconds: int
    expired: bool
    planLevel: str
    isUnlimited: bool = False
    periodKey: str


# ── Free conversation: removed from every plan on 2026-11-12; locked for everyone but admins ──
class ConversationCreditStatus(BaseModel):
    limitSeconds: int
    consumedSeconds: int
    remainingSeconds: int
    expired: bool
    planLevel: str
    isFree: bool
    isUnlimited: bool = False
    periodLabel: str
