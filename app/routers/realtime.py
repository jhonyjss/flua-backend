"""POST /api/realtime/session — OpenAI Realtime ephemeral client secret."""
from fastapi import APIRouter, Depends

from app.core.auth import AuthUser
from app.core.rate_limit import rate_limited
from app.schemas.realtime import RealtimeSessionRequest, RealtimeSessionResponse
from app.services import realtime

router = APIRouter(prefix="/api/realtime", tags=["realtime"])


@router.post("/session", response_model=RealtimeSessionResponse)
async def create_session(
    body: RealtimeSessionRequest,
    user: AuthUser = Depends(rate_limited("realtime", max_requests=20, window_seconds=60)),
) -> RealtimeSessionResponse:
    result = await realtime.create_session(body)
    return RealtimeSessionResponse(success=True, **result)
