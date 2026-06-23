"""User-data endpoints consumed by the Nuxt service layer (TanStack Query)."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import AuthUser, get_current_user
from app.schemas.users import (
    CompletedLessons,
    DashboardStats,
    RecentSession,
    SkillAverages,
    SkillWeeklyPoint,
    Streak,
    SubscriptionInfo,
    UpdateProfileRequest,
    UserProfile,
)
from app.services import user_data

router = APIRouter(prefix="/api/users/me", tags=["users"])


@router.get("/profile", response_model=UserProfile)
async def get_profile(user: AuthUser = Depends(get_current_user)) -> UserProfile:
    profile = await user_data.get_profile(user.id)
    if not profile:
        raise HTTPException(404, "Perfil não encontrado")
    return profile


@router.patch("/profile", response_model=UserProfile)
async def update_profile(
    body: UpdateProfileRequest, user: AuthUser = Depends(get_current_user),
) -> UserProfile:
    profile = await user_data.update_profile(user.id, body)
    if not profile:
        raise HTTPException(404, "Perfil não encontrado")
    return profile


@router.get("/dashboard-stats", response_model=DashboardStats)
async def dashboard_stats(user: AuthUser = Depends(get_current_user)) -> DashboardStats:
    return await user_data.get_dashboard_stats(user.id)


@router.get("/streak", response_model=Streak)
async def streak(user: AuthUser = Depends(get_current_user)) -> Streak:
    return await user_data.get_streak(user.id)


@router.get("/skill-averages", response_model=SkillAverages)
async def skill_averages(
    language: str = Query("en"), user: AuthUser = Depends(get_current_user),
) -> SkillAverages:
    return await user_data.get_skill_averages(user.id, language)


@router.get("/skill-weekly", response_model=list[SkillWeeklyPoint])
async def skill_weekly(
    language: str = Query("en"), user: AuthUser = Depends(get_current_user),
) -> list[SkillWeeklyPoint]:
    return await user_data.get_skill_weekly(user.id, language)


@router.get("/completed-lessons", response_model=CompletedLessons)
async def completed_lessons(user: AuthUser = Depends(get_current_user)) -> CompletedLessons:
    return CompletedLessons(lessonIds=await user_data.get_completed_lesson_ids(user.id))


@router.get("/sessions", response_model=list[RecentSession])
async def sessions(
    limit: int = Query(default=10, ge=1, le=50),
    user: AuthUser = Depends(get_current_user),
) -> list[RecentSession]:
    return await user_data.get_recent_sessions(user.id, limit)


@router.get("/subscription", response_model=SubscriptionInfo)
async def subscription(user: AuthUser = Depends(get_current_user)) -> SubscriptionInfo:
    return await user_data.get_subscription(user.id)
