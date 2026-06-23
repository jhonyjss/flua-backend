"""Schemas for TTS (/api/avatar/speak) and STT (/api/ai/transcribe)."""
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

_SRC = Path(__file__).resolve().parents[2] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from speech.schemas import CorrectionDetail, SpeechCorrectionRequest, SpeechCorrectionResponse

TtsProvider = Literal["elevenlabs", "google", "openai", "deepgram", "browser"]


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    voiceId: str = "default"
    ttsProvider: TtsProvider = "google"
    languageCode: str = "en-US"


class SpeakResponse(BaseModel):
    success: bool
    audioBase64: str | None = None
    provider: str
    error: str | None = None


class TranscribeResponse(BaseModel):
    success: bool
    transcript: str = ""
    confidence: float | None = None
    error: str | None = None
