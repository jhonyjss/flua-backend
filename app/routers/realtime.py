"""POST /api/realtime/session — OpenAI Realtime ephemeral client secret."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthUser
from app.core.rate_limit import rate_limited
from app.schemas.realtime import RealtimeSessionRequest, RealtimeSessionResponse
from app.services import conversation_credits, realtime

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


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
    result = await realtime.create_session(body, user=user)
    return RealtimeSessionResponse(success=True, **result)
