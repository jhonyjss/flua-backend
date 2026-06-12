"""Pydantic schemas for the AI endpoints (parity with the Nuxt server/api/ai)."""
from typing import Literal

from pydantic import BaseModel, Field

UserLevel = Literal["beginner", "intermediate", "advanced"]


# ── Grammar analysis ─────────────────────────────────────────────────
class GrammarAnalysisRequest(BaseModel):
    userMessage: str = Field(min_length=1, max_length=2000)
    expectedPhrases: list[str] = []
    userLevel: UserLevel = "beginner"
    topicContext: str = ""
    previousMistakes: list[str] = []


GrammarCategory = Literal[
    "verb-tense", "subject-verb", "word-order", "article",
    "preposition", "pronunciation", "vocabulary", "other",
]


class GrammarIssue(BaseModel):
    original: str
    correction: str
    explanation: str
    explanationPt: str
    category: GrammarCategory = "other"
    severity: Literal["minor", "important", "critical"] = "minor"


class GrammarAnalysisResult(BaseModel):
    success: bool
    hasErrors: bool = False
    issues: list[GrammarIssue] = []
    correctedMessage: str | None = None
    encouragement: str | None = None
    encouragementPt: str | None = None
    phrasesUsed: list[str] = []
    overallScore: int = Field(default=0, ge=0, le=100)
    error: str | None = None


# ── Conversation response ────────────────────────────────────────────
class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ConversationResponseRequest(BaseModel):
    messages: list[ConversationTurn] = Field(min_length=1)
    userLevel: UserLevel = "beginner"
    scenario: str = ""
    language: Literal["en", "es"] = "en"


class ConversationResponseResult(BaseModel):
    success: bool
    reply: str = ""
    error: str | None = None


# ── Help answer ──────────────────────────────────────────────────────
class HelpAnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    lessonContext: str = ""
    userLevel: UserLevel = "beginner"


class HelpAnswerResult(BaseModel):
    success: bool
    answer: str = ""
    answerPt: str = ""
    error: str | None = None


# ── Learning recommendations ─────────────────────────────────────────
class GrammarProgressItem(BaseModel):
    topic: str
    masteryLevel: float = 0
    exercisesCompleted: int = 0
    exercisesCorrect: int = 0


class VocabularyStats(BaseModel):
    total: int = 0
    learning: int = 0
    mastered: int = 0
    dueForReview: int = 0


class SessionHistoryItem(BaseModel):
    lessonId: str
    goalsCompleted: int = 0
    goalsTotal: int = 0
    messagesExchanged: int = 0
    correctionsReceived: int = 0
    elapsedSeconds: int = 0
    rating: float | None = None


class LearningRecommendationsRequest(BaseModel):
    userLevel: UserLevel = "beginner"
    grammarProgress: list[GrammarProgressItem] = []
    vocabularyStats: VocabularyStats = VocabularyStats()
    sessionHistory: list[SessionHistoryItem] = []
    streakDays: int = 0
    totalLessonsCompleted: int = 0


class FocusArea(BaseModel):
    title: str
    description: str
    severity: Literal["low", "medium", "high"] = "medium"


class LearningRecommendationsResult(BaseModel):
    success: bool
    focusAreas: list[FocusArea] = []
    recommendedTopics: list[str] = []
    motivationPt: str = ""
    error: str | None = None
