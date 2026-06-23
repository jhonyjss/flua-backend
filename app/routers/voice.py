"""Voice endpoints — chat + usage."""
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthUser
from app.core.config import get_settings
from app.core.rate_limit import rate_limited
from app.schemas.voice import (
    VoiceChatRequest,
    VoiceChatResult,
    VoiceUsageGetResult,
    VoiceUsagePostRequest,
    VoiceUsagePostResult,
)
from app.services.voice.chat import voice_chat
from app.services.voice.usage import get_used_minutes, record_minutes

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/chat", response_model=VoiceChatResult)
async def chat(
    body: VoiceChatRequest,
    user: AuthUser = Depends(rate_limited("voice-chat", max_requests=30, window_seconds=60)),
) -> VoiceChatResult:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(503, "OpenAI API key not configured")
    try:
        reply = await voice_chat(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return VoiceChatResult(reply=reply)


@router.get("/usage", response_model=VoiceUsageGetResult)
async def usage_get(user: AuthUser = Depends(rate_limited("voice-usage", max_requests=60, window_seconds=60))) -> VoiceUsageGetResult:
    used = await get_used_minutes(user.id)
    return VoiceUsageGetResult(used_minutes=used)


@router.post("/usage", response_model=VoiceUsagePostResult)
async def usage_post(
    body: VoiceUsagePostRequest,
    user: AuthUser = Depends(rate_limited("voice-usage", max_requests=60, window_seconds=60)),
) -> VoiceUsagePostResult:
    minutes = max(0.0, min(body.minutes, 120.0))
    if minutes <= 0:
        return VoiceUsagePostResult(ok=True, minutes=0)
    recorded = await record_minutes(user.id, minutes, body.engine)
    return VoiceUsagePostResult(ok=True, minutes=recorded)
