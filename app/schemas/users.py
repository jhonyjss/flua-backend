"""Schemas for user-data endpoints (/api/users/me/*).

Field names are camelCase to mirror the frontend mappers (useAuth profile map
and the DashStats interface used by the dashboards).
"""
from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    id: str
    fullName: str | None = None
    avatarUrl: str | None = None
    createdAt: str | None = None
    xp: int = 0
    level: int = 1
    englishLevel: str | None = None
    placementLevel: str | None = None
    explanationLanguage: str = "pt"
    targetLanguage: str = "en"
    learningGoals: list[str] = []


class UpdateProfileRequest(BaseModel):
    fullName: str | None = Field(default=None, max_length=120)
    explanationLanguage: str | None = Field(default=None, pattern="^(pt|en)$")
    targetLanguage: str | None = Field(default=None, pattern="^(en|es)$")
    learningGoals: list[str] | None = None


class RecentSession(BaseModel):
    id: str
    lesson_id: str | None = None
    started_at: str | None = None
    rating: float | None = None
    elapsed_seconds: int = 0
    status: str | None = None


class DashboardStats(BaseModel):
    xp: int = 0
    level: int = 1
    englishLevel: str | None = None
    lessonsCompleted: int = 0
    lessonsInProgress: int = 0
    totalTimeMinutes: int = 0
    totalSessions: int = 0
    totalGoalsCompleted: int = 0
    averageRating: float = 0
    recentSessions: list[RecentSession] = []


class Streak(BaseModel):
    current_streak: int = 0
    longest_streak: int = 0
    total_practice_days: int = 0
    last_practice_date: str | None = None
    weekly_activity: list[str] = []


class CompletedLessons(BaseModel):
    lessonIds: list[str]


class SubscriptionInfo(BaseModel):
    isSubscribed: bool = False
    planLevel: str | None = None
    planName: str | None = None
    status: str | None = None
    cancelAtPeriodEnd: bool = False
    currentPeriodEnd: str | None = None


class SkillAverages(BaseModel):
    """Confidence-weighted per-skill averages (from user_skill_averages).

    `evaluationsCount = 0` means no evaluations yet → the dashboard keeps its
    empty-state fallback.
    """

    grammar: int = 0
    vocabulary: int = 0
    pronunciation: int = 0
    conversation: int = 0
    comprehension: int = 0
    evaluationsCount: int = 0


class SkillWeeklyPoint(BaseModel):
    week: str
    grammar: int = 0
    vocabulary: int = 0
    pronunciation: int = 0
    conversation: int = 0
