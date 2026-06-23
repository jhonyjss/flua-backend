"""Schemas for POST /api/ai/evaluate-lesson (hybrid skill evaluation)."""

from typing import Literal

from pydantic import BaseModel, Field

UserLevel = Literal["beginner", "intermediate", "advanced"]
Severity = Literal["high", "medium", "low"]


class EvalTurn(BaseModel):
    role: Literal["student", "tutor"]
    text: str = Field(max_length=2000)


class LessonContext(BaseModel):
    title: str = ""
    grammarFocus: str = ""
    vocabulary: list[str] = []


class SessionMetrics(BaseModel):
    correctionsReceived: int = 0
    elapsedSeconds: int = 0
    objectivesCompleted: int = 0
    objectivesTotal: int = 0


class EvaluateLessonRequest(BaseModel):
    sessionId: str = Field(min_length=1, max_length=200)
    lessonId: str = Field(min_length=1, max_length=200)
    language: str = "en"
    level: UserLevel = "beginner"
    lessonContext: LessonContext = LessonContext()
    turns: list[EvalTurn] = []
    # Guided-practice phrase scores (from speechEvaluation) — strong signal.
    phraseScores: list[int] = []
    # Average word-level STT confidence (0–1) when available — phase 2 pronunciation.
    sttConfidence: float | None = Field(default=None, ge=0, le=1)
    sessionMetrics: SessionMetrics = SessionMetrics()


class SkillScores(BaseModel):
    grammar: int = Field(ge=0, le=100)
    vocabulary: int = Field(ge=0, le=100)
    pronunciation: int = Field(ge=0, le=100)
    conversation: int = Field(ge=0, le=100)
    comprehension: int = Field(ge=0, le=100)


class FocusArea(BaseModel):
    title: str
    description: str = ""
    severity: Severity = "medium"
    skill: str = ""


class LessonEvaluationResult(BaseModel):
    success: bool
    skipped: bool = False
    scores: SkillScores | None = None
    deterministic: dict | None = None
    llmScores: dict | None = None
    summaryPt: str | None = None
    strengths: list[str] = []
    focusAreas: list[FocusArea] = []
    evidence: list[str] = []
    confidence: float = 0.5
    turnsCount: int = 0
    error: str | None = None
