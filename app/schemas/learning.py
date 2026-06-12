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
