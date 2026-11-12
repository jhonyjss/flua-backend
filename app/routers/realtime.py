"""POST /api/realtime/session — OpenAI Realtime ephemeral client secret; /session-metrics — its counters."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthUser
from app.core.rate_limit import rate_limited
from app.schemas.learning import OkResponse
from app.schemas.realtime import (
    RealtimeSessionRequest,
    RealtimeSessionResponse,
    SessionMetricsRequest,
)
from app.services import (
    conversation_credits,
    guided_access,
    lesson_timer,
    realtime,
    voice_metrics,
    voice_minutes,
)

router = APIRouter(prefix="/api/realtime", tags=["realtime"])

MONTH_SPENT = {
    "code": "voice_minutes_exhausted",
    "message": "Seus minutos de aula com a Flua deste mês acabaram. Eles voltam no dia 1º.",
}


async def _guard_guided_lesson(body: RealtimeSessionRequest, user: AuthUser) -> None:
    """Guided voice lessons: subscribers, or one of a non-subscriber's trial lessons, within the
    lesson's time budget and, for subscribers, the month's minutes. Time is checked first so a spent
    lesson never takes a trial."""
    if await conversation_credits.is_admin(user.id):
        return
    time = await lesson_timer.get_status(user.id, body.lessonId)
    if time["expiredReason"] == "month":
        raise HTTPException(status_code=403, detail=MONTH_SPENT)
    if time["expired"]:
        raise HTTPException(
            status_code=403,
            detail={"code": "lesson_time_expired", "message": "O tempo desta aula acabou."},
        )
    access = await guided_access.authorize(user.id, body.lessonId)
    if access.can_start:
        return
    if access.reason == "trial_used":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "guided_trial_used",
                "message": (
                    "Aulas com a Flua são para assinantes. "
                    f"Suas {guided_access.TRIAL_LIMIT} aulas de teste já foram usadas."
                ),
                "trialLessonId": access.trial_lesson_id,
                "trialsUsed": access.trials_used,
                "trialLimit": guided_access.TRIAL_LIMIT,
            },
        )
    raise HTTPException(
        status_code=403,
        detail={"code": "guided_lesson_unavailable", "message": "Não conseguimos liberar a aula agora."},
    )


@router.post("/session", response_model=RealtimeSessionResponse)
async def create_session(
    body: RealtimeSessionRequest,
    user: AuthUser = Depends(rate_limited("realtime", max_requests=20, window_seconds=60)),
) -> RealtimeSessionResponse:
    # Free conversation was removed from every plan (2026-11-12): only admins still get it, and the
    # check lives here so a client can't mint OpenAI sessions past the plan by calling the API
    # directly. Lessons spend the month's pool of Flua minutes (voice_minutes); guided lessons also
    # keep their own per-lesson budget (lesson_timer).
    if body.mode == "free_practice":
        status = await conversation_credits.get_status(user.id)
        if not conversation_credits.can_converse(status):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "conversation_not_available",
                    "message": "A conversa livre com a Flua não faz mais parte dos planos.",
                    "planLevel": status.get("planLevel"),
                    "expired": status.get("expired"),
                },
            )
    if body.mode == "guided_lesson":
        await _guard_guided_lesson(body, user)
    if body.mode == "lesson" and (await voice_minutes.get_status(user.id))["expired"]:
        raise HTTPException(status_code=403, detail=MONTH_SPENT)
    result = await realtime.create_session(body, user=user)
    return RealtimeSessionResponse(success=True, **result)


@router.post("/session-metrics", response_model=OkResponse, status_code=201)
async def save_session_metrics(
    body: SessionMetricsRequest,
    # One row per session: a few a minute leave room for quick restarts, not for a loop.
    user: AuthUser = Depends(rate_limited("realtime_metrics", max_requests=6, window_seconds=60)),
) -> OkResponse:
    """One row of counters per voice session, sent once by the client when it ends."""
    await voice_metrics.save(user.id, body)
    return OkResponse()
