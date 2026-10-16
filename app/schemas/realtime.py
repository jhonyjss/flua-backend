"""Schemas for the OpenAI Realtime ephemeral session endpoint."""
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

RealtimeVoice = Literal[
    "alloy", "ash", "ballad", "cedar", "coral", "echo", "marin", "sage", "shimmer", "verse",
]


Phrase = Annotated[str, Field(max_length=160)]


class GuidedItem(BaseModel):
    """One concept of the lesson, taught then practised: repeat it, then say it alone."""
    id: str = Field(min_length=1, max_length=64)
    english: Phrase = Field(min_length=1)
    portuguese: Phrase = ""
    note: str = Field("", max_length=200)
    # The "sua vez" request in Portuguese; empty lets Flua write it from the phrase and note.
    cue: str = Field("", max_length=200)
    accepts: list[Phrase] = Field(default_factory=list, max_length=4)


class GuidedPlan(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    # Completes "hoje ele vai aprender a …" (the app's Lesson.skill).
    skill: str = Field(min_length=1, max_length=120)
    items: list[GuidedItem] = Field(min_length=1, max_length=8)


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
    # "guided_lesson" is the app's voice lesson: the app owns the script and Flua
    # reports each evaluation through the registrar_resultado tool.
    mode: Literal["lesson", "free_practice", "guided_lesson"] = "lesson"
    # Free practice only: a theme the client already chose (the app sends the
    # learner's unit, e.g. "Primeiros contatos — Cumprimentar e se apresentar").
    # Flua opens on it instead of the goal menu. Empty keeps the menu (the site).
    topic: str = ""
    # Guided lesson only. lessonId keys the trial and the per-lesson time budget.
    lessonId: str = Field("", max_length=64, pattern=r"^[a-z0-9-]*$")
    plan: GuidedPlan | None = None
    resumeFromItem: int = Field(0, ge=0)
    # Turn-taking: "educational" (default) tolerates long learner pauses and lets
    # the CLIENT decide when Flua responds (no barge-in); "responsive" keeps the
    # snappy auto-reply VAD (opt-in / future premium).
    turnMode: Literal["educational", "responsive", "conversational"] = "educational"
    pipelineMode: bool = False

    @model_validator(mode="after")
    def _guided_lesson_needs_a_plan(self) -> "RealtimeSessionRequest":
        if self.mode != "guided_lesson":
            return self
        if not self.lessonId or self.plan is None:
            raise ValueError("guided_lesson needs lessonId and plan")
        if self.resumeFromItem >= len(self.plan.items):
            raise ValueError("resumeFromItem must point at an item of the plan")
        return self


class GuidedLessonAccess(BaseModel):
    """What the app shows on a lesson; the session mint is the one that decides."""
    canStart: bool
    reason: Literal["subscriber", "trial_available", "trial_in_progress", "trial_used", "unavailable"]
    trialLessonId: str | None = None


class RealtimeSessionResponse(BaseModel):
    success: bool
    clientSecret: str | None = None
    model: str | None = None
    instructions: str | None = None
    error: str | None = None
