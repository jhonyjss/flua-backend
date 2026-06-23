"""Avatar endpoints — speak, tts-whisper, model proxy."""
import base64

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.auth import AuthUser
from app.core.rate_limit import rate_limited
from app.schemas.avatar import TtsWhisperRequest, TtsWhisperResult
from app.schemas.speech import SpeakRequest, SpeakResponse
from app.services import tts
from app.services.avatar.model_proxy import fetch_model
from app.services.avatar.tts_whisper import tts_whisper

router = APIRouter(prefix="/api/avatar", tags=["avatar"])


@router.post("/speak", response_model=SpeakResponse)
async def speak(
    body: SpeakRequest,
    user: AuthUser = Depends(rate_limited("tts", max_requests=120, window_seconds=60)),
) -> SpeakResponse:
    if body.ttsProvider == "browser":
        return SpeakResponse(success=True, provider="browser")

    audio = await tts.synthesize(body.text, body.ttsProvider, body.voiceId, body.languageCode)
    return SpeakResponse(
        success=True,
        provider=body.ttsProvider,
        audioBase64=base64.b64encode(audio).decode("ascii"),
    )


@router.post("/tts-whisper", response_model=TtsWhisperResult)
async def tts_whisper_route(
    body: TtsWhisperRequest,
    user: AuthUser = Depends(rate_limited("tts-whisper", max_requests=60, window_seconds=60)),
) -> TtsWhisperResult:
    return await tts_whisper(body)


@router.get("/model")
async def model_proxy(
    url: str = Query(..., min_length=1),
    user: AuthUser = Depends(rate_limited("avatar-model", max_requests=30, window_seconds=60)),
) -> Response:
    return await fetch_model(url)
