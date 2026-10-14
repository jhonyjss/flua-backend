"""POST /api/realtime/session — OpenAI Realtime ephemeral client secret."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthUser
from app.core.rate_limit import rate_limited
from app.schemas.realtime import RealtimeSessionRequest, RealtimeSessionResponse
from app.services import conversation_credits, guided_access, lesson_timer, realtime

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


async def _guard_guided_lesson(body: RealtimeSessionRequest, user: AuthUser) -> None:
    """Guided voice lessons: subscribers, or a non-subscriber's single trial lesson, within the
    lesson's time budget. Time is checked first so a spent lesson never claims the trial."""
    if await conversation_credits.is_admin(user.id):
        return
    time = await lesson_timer.get_status(user.id, body.lessonId)
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
                "message": "Aulas com a Flua são para assinantes. Sua aula de teste já foi usada.",
                "trialLessonId": access.trial_lesson_id,
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
    # Free conversation spends the plan's conversation minutes (paid-only, as on the site): the
    # server checks them here, so a client can't mint OpenAI sessions past the plan by calling the
    # API directly. Guided lessons keep their own per-lesson time budget (lesson_timer).
    if body.mode == "free_practice":
        status = await conversation_credits.get_status(user.id)
        if not conversation_credits.can_converse(status):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "conversation_not_available",
                    "message": "Conversa com a Flua disponível para assinantes com minutos no período.",
                    "planLevel": status.get("planLevel"),
                    "expired": status.get("expired"),
                },
            )
    if body.mode == "guided_lesson":
        await _guard_guided_lesson(body, user)
    result = await realtime.create_session(body, user=user)
    return RealtimeSessionResponse(success=True, **result)
