"""Learning endpoints — lesson progress, sessions, XP, streaks, achievements.

User-scoped under /api/users/me/* (the JWT subject is the security boundary).
Writes run their multi-step logic server-side (atomic).
"""
from fastapi import APIRouter, Depends

from app.core.auth import AuthUser, get_current_user
from app.schemas.learning import (
    AchievementIds,
    AwardXpRequest,
    ClassSessionRequest,
    CompleteLessonRequest,
    ConversationCreditStatus,
    HeartbeatRequest,
    InProgressLessons,
    LessonProgressRow,
    LessonTimeStatus,
    OkResponse,
    PracticeResult,
    RecordPracticeRequest,
    SaveTopicRequest,
    StartLessonRequest,
    TopicIds,
    UnlockedLessons,
    UnlockLessonRequest,
    XpResult,
)
from app.services import conversation_credits, learning, lesson_timer

router = APIRouter(prefix="/api/users/me", tags=["learning"])


# ── Reads ─────────────────────────────────────────────────────────────
@router.get("/progress", response_model=list[LessonProgressRow])
async def list_progress(user: AuthUser = Depends(get_current_user)) -> list[LessonProgressRow]:
    rows = await learning.list_progress(user.id)
    return [LessonProgressRow.model_validate(r) for r in rows]


@router.get("/unlocked-lessons", response_model=UnlockedLessons)
async def unlocked_lessons(user: AuthUser = Depends(get_current_user)) -> UnlockedLessons:
    return UnlockedLessons(lessonIds=await learning.unlocked_lesson_ids(user.id))


@router.get("/in-progress-lessons", response_model=InProgressLessons)
async def in_progress_lessons(user: AuthUser = Depends(get_current_user)) -> InProgressLessons:
    return InProgressLessons(lessons=await learning.in_progress_lessons(user.id))


@router.get("/lessons/{lesson_id}/topics", response_model=TopicIds)
async def lesson_topics(lesson_id: str, user: AuthUser = Depends(get_current_user)) -> TopicIds:
    return TopicIds(topicIds=await learning.completed_topic_ids(user.id, lesson_id))


# ── Per-lesson time budget (server-enforced; consistent across devices) ──
@router.get("/lessons/{lesson_id}/time", response_model=LessonTimeStatus)
async def lesson_time(lesson_id: str, user: AuthUser = Depends(get_current_user)) -> LessonTimeStatus:
    return LessonTimeStatus(**await lesson_timer.get_status(user.id, lesson_id))


@router.post("/lessons/{lesson_id}/time/heartbeat", response_model=LessonTimeStatus)
async def lesson_time_heartbeat(
    lesson_id: str, body: HeartbeatRequest, user: AuthUser = Depends(get_current_user),
) -> LessonTimeStatus:
    return LessonTimeStatus(**await lesson_timer.add_time(user.id, lesson_id, body.deltaSeconds))


# ── Free-conversation credit pool (free weekly, starter daily, pro unlimited) ──
@router.get("/conversation/time", response_model=ConversationCreditStatus)
async def conversation_time(user: AuthUser = Depends(get_current_user)) -> ConversationCreditStatus:
    return ConversationCreditStatus(**await conversation_credits.get_status(user.id))


@router.post("/conversation/time/heartbeat", response_model=ConversationCreditStatus)
async def conversation_time_heartbeat(
    body: HeartbeatRequest, user: AuthUser = Depends(get_current_user),
) -> ConversationCreditStatus:
    return ConversationCreditStatus(**await conversation_credits.add_time(user.id, body.deltaSeconds))


@router.get("/achievements", response_model=AchievementIds)
async def achievements(user: AuthUser = Depends(get_current_user)) -> AchievementIds:
    return AchievementIds(achievementIds=await learning.unlocked_achievement_ids(user.id))


@router.post("/achievements/{achievement_id}", response_model=OkResponse)
async def unlock_achievement(
    achievement_id: str, user: AuthUser = Depends(get_current_user),
) -> OkResponse:
    await learning.unlock_achievements(user.id, [achievement_id])
    return OkResponse()


# ── Writes ────────────────────────────────────────────────────────────
@router.post("/lessons/{lesson_id}/start", response_model=OkResponse)
async def start_lesson(
    lesson_id: str, body: StartLessonRequest, user: AuthUser = Depends(get_current_user),
) -> OkResponse:
    await learning.start_lesson(user.id, lesson_id, body.sessionId)
    return OkResponse()


@router.post("/lessons/{lesson_id}/complete", response_model=OkResponse)
async def complete_lesson(
    lesson_id: str, body: CompleteLessonRequest, user: AuthUser = Depends(get_current_user),
) -> OkResponse:
    await learning.complete_lesson(user.id, lesson_id, body.model_dump())
    return OkResponse()


@router.post("/lessons/{lesson_id}/topics", response_model=OkResponse)
async def save_topic(
    lesson_id: str, body: SaveTopicRequest, user: AuthUser = Depends(get_current_user),
) -> OkResponse:
    await learning.save_topic_completion(user.id, lesson_id, body.topicId)
    return OkResponse()


@router.post("/lessons/{lesson_id}/unlock", response_model=OkResponse)
async def unlock_lesson(
    lesson_id: str, body: UnlockLessonRequest, user: AuthUser = Depends(get_current_user),
) -> OkResponse:
    await learning.unlock_lesson(user.id, lesson_id, body.unlockedBy)
    return OkResponse()


@router.post("/sessions", response_model=OkResponse, status_code=201)
async def save_session(
    body: ClassSessionRequest, user: AuthUser = Depends(get_current_user),
) -> OkResponse:
    await learning.save_class_session(user.id, body.model_dump(exclude_none=True))
    return OkResponse()


@router.post("/xp", response_model=XpResult)
async def award_xp(body: AwardXpRequest, user: AuthUser = Depends(get_current_user)) -> XpResult:
    result = await learning.award_xp(user.id, body.amount)
    if result is None:
        # No profile row — return a no-op result rather than 500
        return XpResult(newXp=0, newLevel=1, leveledUp=False)
    return XpResult.model_validate(result)


@router.post("/practice", response_model=PracticeResult)
async def record_practice(
    body: RecordPracticeRequest, user: AuthUser = Depends(get_current_user),
) -> PracticeResult:
    result = await learning.record_practice(user.id, body.timeSeconds, body.lessonCompleted)
    return PracticeResult.model_validate(result)
