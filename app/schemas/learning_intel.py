"""Schemas for the learning-intelligence endpoints (/api/users/me/learning/*).

snake_case to mirror the product spec. user_id is NEVER in a request body — it
comes from the authenticated JWT.
"""

from typing import Literal

from pydantic import BaseModel, Field

CEFR = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
VocabType = Literal["word", "phrase", "collocation", "phrasal_verb", "idiom"]
VocabStatus = Literal["new", "learning", "reviewing", "mastered"]


class LearningProfile(BaseModel):
    level: CEFR = "A1"
    native_language: str = "pt-BR"
    learning_goal: str | None = None
    strengths: list[str] = []
    weaknesses: list[str] = []
    preferred_explanation_language: str = "pt-BR"
    pace: Literal["calm", "normal", "fast"] = "calm"


class LearningProfilePatch(BaseModel):
    level: CEFR | None = None
    native_language: str | None = None
    learning_goal: str | None = None
    strengths: list[str] | None = None
    weaknesses: list[str] | None = None
    preferred_explanation_language: str | None = None
    pace: Literal["calm", "normal", "fast"] | None = None


class VocabularyItem(BaseModel):
    id: str
    term: str
    type: VocabType = "word"
    level: str | None = None
    meaning_pt: str | None = None
    examples: list[str] = []
    status: VocabStatus = "new"
    confidence_score: float = 0.30
    times_seen: int = 0
    times_correct: int = 0
    next_review_at: str | None = None


class VocabularyCreate(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    type: VocabType = "word"
    level: str | None = None
    meaning_pt: str | None = None
    examples: list[str] = []


class VocabularyPatch(BaseModel):
    meaning_pt: str | None = None
    examples: list[str] | None = None
    status: VocabStatus | None = None


class ErrorLog(BaseModel):
    id: str
    error_text: str
    correction: str
    category: str = "other"
    count: int = 1
    examples: list[dict] = []
    last_seen_at: str | None = None


class ErrorCreate(BaseModel):
    error_text: str = Field(min_length=1, max_length=300)
    correction: str = Field(min_length=1, max_length=300)
    category: str = "other"
    example_wrong: str | None = None
    example_correct: str | None = None


class ReviewItem(BaseModel):
    id: str
    kind: Literal["vocabulary", "error"]
    ref_id: str
    due_at: str | None = None
    interval_days: int = 0
    reps: int = 0
    status: str = "due"
    term: str | None = None
    meaning_pt: str | None = None
    correction: str | None = None


class ReviewAnswer(BaseModel):
    quality: int = Field(ge=0, le=5, description="0=errou … 5=fácil")


class Recommendation(BaseModel):
    next_activity: str
    reason: str
    items: list[str] = []


class OkResponse(BaseModel):
    success: bool = True


# ── Tutor respond (RAG + guardrails) ─────────────────────────────────────
class TutorRespondRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    language: str = "en"
    level: CEFR | None = None


class TutorSource(BaseModel):
    topic: str | None = None
    level: str | None = None
    similarity: float | None = None


class TutorRespondResult(BaseModel):
    reply: str
    used_context: bool = False
    sources: list[TutorSource] = []


# ── RAG ingestion (admin only) ───────────────────────────────────────────
class RagDocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=80)
    level: CEFR = "A1"
    language: str = "en-pt"
    source: str = "internal_curriculum"
    verified: bool = True
    content: str = Field(min_length=1, max_length=20000)
    metadata: dict = {}


class RagIngestResult(BaseModel):
    document_title: str
    chunks: int
