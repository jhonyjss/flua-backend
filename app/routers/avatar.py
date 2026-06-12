"""TTS endpoint — POST /api/avatar/speak (parity with the Nuxt route)."""
import base64

from fastapi import APIRouter, Depends

from app.core.auth import AuthUser
from app.core.rate_limit import rate_limited
from app.schemas.speech import SpeakRequest, SpeakResponse
from app.services import tts

router = APIRouter(prefix="/api/avatar", tags=["tts"])


@router.post("/speak", response_model=SpeakResponse)
async def speak(
    body: SpeakRequest,
    user: AuthUser = Depends(rate_limited("tts", max_requests=120, window_seconds=60)),
) -> SpeakResponse:
    # Browser fallback: client uses SpeechSynthesis; nothing to synthesize here.
    if body.ttsProvider == "browser":
        return SpeakResponse(success=True, provider="browser")

    audio = await tts.synthesize(body.text, body.ttsProvider, body.voiceId, body.languageCode)
    return SpeakResponse(
        success=True,
        provider=body.ttsProvider,
        audioBase64=base64.b64encode(audio).decode("ascii"),
    )
