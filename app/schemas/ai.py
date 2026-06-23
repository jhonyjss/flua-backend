"""Pydantic schemas — parity with server/api/ai/* (Nuxt contracts)."""
from typing import Any, Literal

from pydantic import BaseModel, Field

UserLevel = Literal["beginner", "intermediate", "advanced"]
ClassLevel = Literal["beginner", "elementary", "intermediate", "advanced"]
ScenarioType = Literal[
    "english-tutor", "spanish-tutor", "job-interview", "restaurant", "travel",
    "shopping", "doctor", "business-meeting", "casual-chat",
    "free-conversation", "free-conversation-es",
]
ValidationMode = Literal["repetition", "free-production"]
AssistAction = Literal["improve", "expand", "translate", "suggest", "simplify", "respond"]
ImageStyle = Literal["realistic", "anime", "digital-art", "fantasy", "cinematic"]
ImageType = Literal["background", "element", "character"]
ImageQuality = Literal["fast", "hd", "4k"]
SttProvider = Literal["deepgram", "whisper"]


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
class NpcCharacter(BaseModel):
    name: str = "Flua"
    role: str = "English tutor"
    personality: str = "warm and encouraging"


class LessonContextBlock(BaseModel):
    currentTopic: str = ""
    currentTopicPt: str = ""
    keyPhrases: list[str] = []
    vocabularyWords: list[str] = []
    grammarPoint: str = ""
    completedTopics: list[str] = []
    pendingTopics: list[str] = []
    currentTopicNumber: int | None = None
    totalTopics: int | None = None


class ConversationHistoryItem(BaseModel):
    role: Literal["user", "npc"]
    message: str


class ConversationResponseRequest(BaseModel):
    userMessage: str = Field(min_length=1, max_length=2000)
    conversationHistory: list[ConversationHistoryItem] = []
    scenario: ScenarioType | str = "english-tutor"
    userLevel: UserLevel = "intermediate"
    npcCharacter: NpcCharacter = Field(default_factory=NpcCharacter)
    learningFocus: str | None = None
    language: Literal["en", "es"] = "en"
    lessonContext: LessonContextBlock | None = None
    teacherMode: bool = False
    portugueseExplanations: bool = False
    studentName: str | None = None
    studentInterests: list[str] | None = None


class ConversationResponseResult(BaseModel):
    success: bool
    response: str = ""
    error: str | None = None


# ── Help answer ──────────────────────────────────────────────────────
class HelpLessonContext(BaseModel):
    currentTopic: str = ""
    currentTopicPt: str = ""
    keyPhrases: list[str] = []
    vocabularyWords: list[str] = []
    grammarPoint: str = ""


class HelpAnswerRequest(BaseModel):
    npcQuestion: str = Field(min_length=1, max_length=2000)
    lessonContext: HelpLessonContext | None = None
    userLevel: UserLevel = "beginner"
    conversationHistory: list[ConversationHistoryItem] = []


class HelpAnswerResult(BaseModel):
    success: bool
    explanationPt: str = ""
    exampleAnswer: str = ""
    error: str | None = None


# ── Validate objective ───────────────────────────────────────────────
class ValidateObjectiveRequest(BaseModel):
    userMessage: str = Field(min_length=1, max_length=2000)
    keyPhrases: list[str] = Field(min_length=1)
    userLevel: str = "beginner"
    validationMode: ValidationMode = "free-production"


LessonEvaluation = Literal[
    "EXACT_MATCH", "ACCEPTABLE_EQUIVALENT", "PARTIALLY_CORRECT",
    "INCORRECT", "INCOMPLETE", "OFF_TOPIC",
]
LessonGoalStatus = Literal["COMPLETED", "NEEDS_RETRY", "IN_PROGRESS"]


class ValidateObjectiveResult(BaseModel):
    success: bool
    match: bool = False
    confidence: float = 0.0
    matchedPhrase: str | None = None
    reason: str = ""
    evaluation: LessonEvaluation = "INCORRECT"
    lessonGoalStatus: LessonGoalStatus = "IN_PROGRESS"
    shouldAdvance: bool = False
    correctedText: str | None = None
    expectedRetry: str | None = None
    tutorMessage: str = ""
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
    vocabularyStats: VocabularyStats = Field(default_factory=VocabularyStats)
    sessionHistory: list[SessionHistoryItem] = []
    streakDays: int = 0
    totalLessonsCompleted: int = 0


class FocusArea(BaseModel):
    title: str
    description: str
    severity: Literal["low", "medium", "high"] = "medium"


class StudyTip(BaseModel):
    title: str
    description: str


class LearningRecommendationsResult(BaseModel):
    success: bool
    focusAreas: list[FocusArea] = []
    studyTips: list[StudyTip] = []
    overallAssessment: str = ""
    overallAssessmentPt: str = ""
    suggestedNextLesson: str = ""
    recommendedTopics: list[str] = []
    motivationPt: str = ""
    error: str | None = None


# ── Generate suggestions ─────────────────────────────────────────────
class SuggestionsLessonContext(BaseModel):
    currentTopic: str = ""
    keyPhrases: list[str] = []
    vocabularyWords: list[str] = []


class GenerateSuggestionsRequest(BaseModel):
    npcMessage: str = Field(min_length=1, max_length=2000)
    conversationHistory: list[ConversationHistoryItem] = []
    scenario: str = "english-tutor"
    userLevel: UserLevel = "intermediate"
    lessonContext: SuggestionsLessonContext | None = None
    suggestionCount: int = 3


class SuggestionItem(BaseModel):
    text: str
    textPt: str
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    usesKeyPhrase: bool = False
    lexicalChunks: list[str] | None = None


class GenerateSuggestionsResult(BaseModel):
    success: bool
    suggestions: list[SuggestionItem] = []
    error: str | None = None


# ── Dynamic examples ─────────────────────────────────────────────────
class DynamicExamplesRequest(BaseModel):
    topic: str
    topicPt: str = ""
    level: UserLevel = "beginner"
    vocabularyWords: list[str] = []
    grammarPoint: str = ""
    keyPhrases: list[str] = []
    previousExamples: list[str] = []
    count: int = 3


class DynamicExampleItem(BaseModel):
    english: str
    portuguese: str
    context: str = ""
    difficulty: str = "beginner"
    vocabularyUsed: list[str] = []
    grammarPointUsed: str | None = None


class DynamicExamplesResult(BaseModel):
    examples: list[DynamicExampleItem] = []
    teachingTip: str | None = None


# ── Assist ───────────────────────────────────────────────────────────
class AssistRequest(BaseModel):
    action: AssistAction
    text: str = Field(min_length=1, max_length=20000)
    context: str | None = None
    field: str | None = None
    targetLanguage: str | None = None


class AssistResult(BaseModel):
    success: bool
    result: str | None = None
    error: str | None = None


# ── Generate class ───────────────────────────────────────────────────
class GenerateClassRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    level: ClassLevel = "beginner"
    category: str = "general"
    language: str = "en"


class GenerateClassResult(BaseModel):
    success: bool
    data: dict[str, Any] | None = None
    usage: dict[str, int] | None = None
    error: str | None = None


# ── Generate room ────────────────────────────────────────────────────
class GenerateRoomRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=5000)
    difficulty: str = "beginner"
    category: str = "general"


class GenerateRoomResult(BaseModel):
    success: bool
    data: dict[str, Any] | None = None
    usage: dict[str, int] | None = None
    error: str | None = None


# ── Generate image ───────────────────────────────────────────────────
class GenerateImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    type: ImageType = "background"
    width: int | None = None
    height: int | None = None
    style: ImageStyle = "realistic"
    quality: ImageQuality | None = None
    roomId: int | None = None
    sceneId: int | None = None
    elementId: str | None = None


class GenerateImageResult(BaseModel):
    success: bool
    imageUrl: str | None = None
    storageUrl: str | None = None
    error: str | None = None


# ── Transcribe ───────────────────────────────────────────────────────
class TranscribeJsonRequest(BaseModel):
    audio: str
    sampleRate: int = 16000
    language: str = "en"
    provider: SttProvider | None = None


class TranscribeWord(BaseModel):
    word: str
    start: float = 0
    end: float = 0
    confidence: float = 0


class TranscribeResult(BaseModel):
    success: bool
    transcript: str = ""
    confidence: float | None = None
    words: list[TranscribeWord] = []
    provider: str | None = None
    detectedLanguage: str | None = None
    error: str | None = None
