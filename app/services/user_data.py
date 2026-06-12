"""User-data reads/writes against Supabase (parity with the Nuxt composables).

Ported queries:
- profiles row             ← useAuth.fetchProfile (camelCase mapping)
- dashboard stats          ← useLessonProgress.getDashboardStats
- completed lesson ids     ← useLessonProgress.getCompletedLessonIds
- recent sessions          ← useLessonProgress.getRecentSessions
- streak                   ← useStreaks.getStreak (user_streaks)
- subscription             ← useSubscription (stripe_subscriptions)

All queries are filtered by the *authenticated* user id (service-role key
bypasses RLS, so the filter is the security boundary).
"""
from app.schemas.users import (
    DashboardStats,
    RecentSession,
    Streak,
    SubscriptionInfo,
    UpdateProfileRequest,
    UserProfile,
)
from app.services import supabase_admin as db


def map_profile(row: dict) -> UserProfile:
    return UserProfile(
        id=row.get("id", ""),
        fullName=row.get("full_name"),
        avatarUrl=row.get("avatar_url"),
        createdAt=row.get("created_at"),
        xp=row.get("xp") or 0,
        level=row.get("level") or 1,
        englishLevel=row.get("english_level"),
        placementLevel=row.get("placement_level"),
        explanationLanguage=row.get("explanation_language") or "pt",
        targetLanguage=row.get("target_language") or "en",
        learningGoals=row.get("learning_goals") or [],
    )


async def get_profile(user_id: str) -> UserProfile | None:
    row = await db.select_one("profiles", {"id": user_id})
    return map_profile(row) if row else None


def build_profile_update(body: UpdateProfileRequest) -> dict:
    """camelCase request → snake_case column updates (only provided fields)."""
    values: dict = {}
    if body.fullName is not None:
        values["full_name"] = body.fullName.strip() or None
    if body.explanationLanguage is not None:
        values["explanation_language"] = body.explanationLanguage
    if body.targetLanguage is not None:
        values["target_language"] = body.targetLanguage
    if body.learningGoals is not None:
        values["learning_goals"] = body.learningGoals
    return values


async def update_profile(user_id: str, body: UpdateProfileRequest) -> UserProfile | None:
    values = build_profile_update(body)
    if values:
        await db.update("profiles", {"id": user_id}, values)
    return await get_profile(user_id)


def compute_dashboard_stats(
    profile_row: dict | None,
    progress_rows: list[dict],
    session_rows: list[dict],
) -> DashboardStats:
    """Pure aggregation — mirrors getDashboardStats in the Nuxt composable."""
    completed = [p for p in progress_rows if p.get("status") == "completed"]
    in_progress = [p for p in progress_rows if p.get("status") == "in_progress"]
    total_seconds = sum(s.get("elapsed_seconds") or 0 for s in session_rows)
    goals = sum(s.get("goals_completed") or 0 for s in session_rows)
    ratings = [s["rating"] for s in session_rows if s.get("rating")]
    return DashboardStats(
        xp=(profile_row or {}).get("xp") or 0,
        level=(profile_row or {}).get("level") or 1,
        englishLevel=(profile_row or {}).get("english_level"),
        lessonsCompleted=len(completed),
        lessonsInProgress=len(in_progress),
        totalTimeMinutes=total_seconds // 60,
        totalSessions=len(session_rows),
        totalGoalsCompleted=goals,
        averageRating=round(sum(ratings) / len(ratings), 2) if ratings else 0,
        recentSessions=[
            RecentSession(
                id=str(s.get("id", "")),
                lesson_id=s.get("lesson_id"),
                started_at=s.get("started_at"),
                rating=s.get("rating"),
                elapsed_seconds=s.get("elapsed_seconds") or 0,
                status=s.get("status"),
            )
            for s in session_rows[:5]
        ],
    )


async def get_dashboard_stats(user_id: str) -> DashboardStats:
    profile_row = await db.select_one("profiles", {"id": user_id})
    progress_rows = await db.select_many("lesson_progress", {"user_id": user_id})
    session_rows = await db.select_many(
        "class_sessions", {"user_id": user_id}, order="started_at.desc",
    )
    return compute_dashboard_stats(profile_row, progress_rows, session_rows)


async def get_completed_lesson_ids(user_id: str) -> list[str]:
    rows = await db.select_many(
        "lesson_progress",
        {"user_id": user_id, "status": "completed"},
        select="lesson_id",
    )
    return [r["lesson_id"] for r in rows if r.get("lesson_id")]


async def get_recent_sessions(user_id: str, limit: int = 10) -> list[RecentSession]:
    rows = await db.select_many(
        "class_sessions", {"user_id": user_id}, order="started_at.desc", limit=limit,
    )
    return [
        RecentSession(
            id=str(r.get("id", "")),
            lesson_id=r.get("lesson_id"),
            started_at=r.get("started_at"),
            rating=r.get("rating"),
            elapsed_seconds=r.get("elapsed_seconds") or 0,
            status=r.get("status"),
        )
        for r in rows
    ]


async def get_streak(user_id: str) -> Streak:
    row = await db.select_one("user_streaks", {"user_id": user_id})
    if not row:
        return Streak()
    return Streak(
        current_streak=row.get("current_streak") or 0,
        longest_streak=row.get("longest_streak") or 0,
        total_practice_days=row.get("total_practice_days") or 0,
        last_practice_date=row.get("last_practice_date"),
        weekly_activity=row.get("weekly_activity") or [],
    )


ACTIVE_STATUSES = {"active", "trialing", "past_due"}


def map_subscription(row: dict | None) -> SubscriptionInfo:
    if not row:
        return SubscriptionInfo()
    status = row.get("status")
    return SubscriptionInfo(
        isSubscribed=status in ACTIVE_STATUSES,
        planLevel=row.get("plan_level") or row.get("plan"),
        planName=row.get("plan_name"),
        status=status,
        cancelAtPeriodEnd=bool(row.get("cancel_at_period_end")),
        currentPeriodEnd=row.get("current_period_end"),
    )


async def get_subscription(user_id: str) -> SubscriptionInfo:
    row = await db.select_one("stripe_subscriptions", {"user_id": user_id})
    return map_subscription(row)
