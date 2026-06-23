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
    # Profile preferences that configure how Flua teaches.
    explanationLanguage: Literal["pt", "en"] = "pt"
    learningGoals: list[str] = []
    # "lesson" follows the structured lesson path; "free_practice" is open,
    # student-led conversation (asks the goal first, no rigid syllabus).
    mode: Literal["lesson", "free_practice"] = "lesson"
    # Turn-taking: "educational" (default) tolerates long learner pauses and lets
    # the CLIENT decide when Flua responds (no barge-in); "responsive" keeps the
    # snappy auto-reply VAD (opt-in / future premium).
    turnMode: Literal["educational", "responsive"] = "educational"
    pipelineMode: bool = False


class RealtimeSessionResponse(BaseModel):
    success: bool
    clientSecret: str | None = None
    model: str | None = None
    instructions: str | None = None
    error: str | None = None
