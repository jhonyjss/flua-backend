"""Schemas for /api/voice/* endpoints."""
from typing import Literal

from pydantic import BaseModel, Field

VoiceEngine = Literal["realtime", "pipeline", "pipeline-premium"]


class VoiceChatMessage(BaseModel):
    role: Literal["user", "assistant", "system", "developer"] = "user"
    content: str = ""


class VoiceChatRequest(BaseModel):
    messages: list[VoiceChatMessage] = []
    model: str | None = None
    maxTokens: int = 512
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    scenario: str = "english-tutor"
    language: Literal["en", "es"] = "en"
    lessonContext: str = ""
    studentName: str = ""


class VoiceChatResult(BaseModel):
    reply: str = ""


class VoiceUsagePostRequest(BaseModel):
    minutes: float = Field(ge=0, le=120)
    engine: VoiceEngine = "realtime"


class VoiceUsagePostResult(BaseModel):
    ok: bool = True
    minutes: float = 0


class VoiceUsageGetResult(BaseModel):
    used_minutes: float = 0
