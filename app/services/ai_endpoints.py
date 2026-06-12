"""Prompt builders + result parsing for the AI endpoints.

Prompts are ported from the Nuxt server (server/api/ai/*). Builders and
parsers are pure functions so they can be unit-tested without network.
"""
from app.schemas.ai import (
    ConversationResponseRequest,
    GrammarAnalysisRequest,
    GrammarAnalysisResult,
    HelpAnswerRequest,
    LearningRecommendationsRequest,
    LearningRecommendationsResult,
)
from app.services.anthropic_client import extract_json

# ── Grammar analysis ─────────────────────────────────────────────────

def build_grammar_system_prompt(req: GrammarAnalysisRequest) -> str:
    phrases = ", ".join(f'"{p}"' for p in req.expectedPhrases) or "none provided"
    mistakes = "; ".join(req.previousMistakes) or "none recorded"
    return (
        "You are an expert English language teacher analyzing a student's response.\n"
        f"Student level: {req.userLevel}. Topic context: {req.topicContext or 'general practice'}.\n"
        f"Expected phrases to practice: {phrases}. Previous recurring mistakes: {mistakes}.\n\n"
        "Analyze the student's message for grammar, vocabulary and word-order issues. "
        "Be encouraging — minor slips at lower levels can be ignored. "
        "Respond ONLY with a JSON object using exactly these keys: "
        '{"hasErrors": bool, "issues": [{"original": str, "correction": str, '
        '"explanation": str (English), "explanationPt": str (Portuguese), '
        '"category": "verb-tense"|"subject-verb"|"word-order"|"article"|"preposition"|"pronunciation"|"vocabulary"|"other", '
        '"severity": "minor"|"important"|"critical"}], '
        '"correctedMessage": str, "encouragement": str (English), "encouragementPt": str (Portuguese), '
        '"phrasesUsed": [str], "overallScore": int 0-100}'
    )


def parse_grammar_result(raw_text: str) -> GrammarAnalysisResult:
    data = extract_json(raw_text)
    data.setdefault("success", True)
    score = data.get("overallScore", 0)
    data["overallScore"] = max(0, min(100, int(score) if isinstance(score, (int, float)) else 0))
    return GrammarAnalysisResult.model_validate({**data, "success": True})


# ── Conversation response ────────────────────────────────────────────

def build_conversation_system_prompt(req: ConversationResponseRequest) -> str:
    lang = "Spanish" if req.language == "es" else "English"
    return (
        f"You are Flua, a friendly {lang} tutor for Brazilian learners. "
        f"Student level: {req.userLevel}. Scenario: {req.scenario or 'free conversation'}.\n"
        f"Reply in {lang}, briefly (1-3 sentences), warm and encouraging. "
        "Gently recast mistakes instead of lecturing. Ask one follow-up question to keep the conversation going."
    )


# ── Help answer ──────────────────────────────────────────────────────

def build_help_system_prompt(req: HelpAnswerRequest) -> str:
    return (
        "You are Flua, an English teacher helping a Brazilian student during a lesson.\n"
        f"Student level: {req.userLevel}. Lesson context: {req.lessonContext[:2000] or 'general English'}.\n"
        "Answer the student's question clearly and briefly. Respond ONLY with JSON: "
        '{"answer": str (English, simple), "answerPt": str (Portuguese explanation)}'
    )


# ── Learning recommendations ─────────────────────────────────────────

def build_recommendations_system_prompt() -> str:
    return (
        "You are an English-learning coach. Given the student's stats, identify what to "
        "focus on next. Respond ONLY with JSON: "
        '{"focusAreas": [{"title": str (Portuguese), "description": str (Portuguese), '
        '"severity": "low"|"medium"|"high"}], '
        '"recommendedTopics": [str], "motivationPt": str (short, Portuguese)}'
    )


def build_recommendations_user_message(req: LearningRecommendationsRequest) -> str:
    grammar = "; ".join(
        f"{g.topic}: mastery {g.masteryLevel}, {g.exercisesCorrect}/{g.exercisesCompleted} correct"
        for g in req.grammarProgress
    ) or "no grammar data"
    sessions = f"{len(req.sessionHistory)} recent sessions"
    return (
        f"Level: {req.userLevel}. Streak: {req.streakDays} days. "
        f"Lessons completed: {req.totalLessonsCompleted}. Grammar: {grammar}. "
        f"Vocabulary: {req.vocabularyStats.mastered}/{req.vocabularyStats.total} mastered, "
        f"{req.vocabularyStats.dueForReview} due for review. Sessions: {sessions}."
    )


def parse_recommendations_result(raw_text: str) -> LearningRecommendationsResult:
    data = extract_json(raw_text)
    return LearningRecommendationsResult.model_validate({**data, "success": True})
