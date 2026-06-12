"""Schemas for TTS (/api/avatar/speak) and STT (/api/ai/transcribe)."""
from typing import Literal

from pydantic import BaseModel, Field

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
