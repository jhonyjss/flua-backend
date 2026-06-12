"""Schemas for the OpenAI Realtime ephemeral session endpoint."""
from typing import Literal

from pydantic import BaseModel

RealtimeVoice = Literal[
    "alloy", "ash", "ballad", "cedar", "coral", "echo", "marin", "sage", "shimmer", "verse",
]


class RealtimeSessionRequest(BaseModel):
    level: Literal["beginner", "intermediate", "advanced"] = "beginner"
    scenario: str = "english-tutor"
    voice: RealtimeVoice = "coral"
    lessonContext: str = ""
    studentName: str = ""
    language: Literal["en", "es"] = "en"
    pipelineMode: bool = False


class RealtimeSessionResponse(BaseModel):
    success: bool
    clientSecret: str | None = None
    model: str | None = None
    instructions: str | None = None
    error: str | None = None
