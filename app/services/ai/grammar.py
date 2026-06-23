"""Grammar analysis — port of grammar-analysis.post.ts."""
from app.schemas.ai import GrammarAnalysisRequest, GrammarAnalysisResult
from app.services.anthropic_client import complete, extract_json


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
    score = data.get("overallScore", 0)
    data["overallScore"] = max(0, min(100, int(score) if isinstance(score, (int, float)) else 0))
    return GrammarAnalysisResult.model_validate({**data, "success": True})


async def analyze_grammar(req: GrammarAnalysisRequest) -> GrammarAnalysisResult:
    try:
        raw = await complete(build_grammar_system_prompt(req), req.userMessage, max_tokens=1024, temperature=0.2)
        return parse_grammar_result(raw)
    except ValueError:
        return GrammarAnalysisResult(success=False, error="Não foi possível analisar agora.")
