"""Schemas for extended /api/avatar/* endpoints."""
from pydantic import BaseModel, Field


class TtsWhisperRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    voiceId: str = "alloy"
    languageCode: str = "en-US"


class TtsWhisperResult(BaseModel):
    success: bool
    audioBase64: str = ""
    words: list[str] = []
    wtimes: list[float] = []
    wdurations: list[float] = []
    provider: str = "openai"
    error: str | None = None
