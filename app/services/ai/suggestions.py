"""Generate suggestions — port of generate-suggestions.post.ts."""
from app.core.config import get_settings
from app.schemas.ai import GenerateSuggestionsRequest, GenerateSuggestionsResult, SuggestionItem
from app.services.anthropic_client import complete, extract_json

LEVEL_GUIDE = {
    "beginner": "Simple vocabulary, short sentences (5-10 words).",
    "intermediate": "Moderate vocabulary, natural sentences (10-15 words).",
    "advanced": "Sophisticated vocabulary, complex sentences (15-20 words).",
}

MOCK = [
    SuggestionItem(text="I think that's a great idea!", textPt="Acho que é uma ótima ideia!", difficulty="easy", usesKeyPhrase=False),
    SuggestionItem(text="Could you tell me more about that?", textPt="Pode me contar mais sobre isso?", difficulty="medium", usesKeyPhrase=False),
    SuggestionItem(text="That reminds me of something similar I experienced.", textPt="Isso me lembra algo parecido que eu vivi.", difficulty="hard", usesKeyPhrase=False),
]


async def generate_suggestions(req: GenerateSuggestionsRequest) -> GenerateSuggestionsResult:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return GenerateSuggestionsResult(success=True, suggestions=MOCK[: req.suggestionCount])

    history = "\n".join(
        f"{'Student' if m.role == 'user' else 'Teacher'}: {m.message}"
        for m in req.conversationHistory[-4:]
    )
    lesson = ""
    if req.lessonContext:
        lc = req.lessonContext
        lesson = (
            f"\nTopic: {lc.currentTopic}\nKey phrases: {', '.join(lc.keyPhrases)}\n"
            f"Vocabulary: {', '.join(lc.vocabularyWords)}"
        )
    system = f"""Generate {req.suggestionCount} reply suggestions for an English student.
Scenario: {req.scenario}. Level: {req.userLevel}. {LEVEL_GUIDE[req.userLevel]}
{lesson}
Return JSON: {{"suggestions":[{{"text":str,"textPt":str,"difficulty":"easy"|"medium"|"hard","usesKeyPhrase":bool,"lexicalChunks":[str]}}]}}"""
    user = f"Teacher said: \"{req.npcMessage}\"\n\nRecent:\n{history}\n\nGenerate suggestions."
    try:
        raw = await complete(system, user, max_tokens=800, temperature=0.5, model=settings.anthropic_model_haiku)
        data = extract_json(raw)
        items = [SuggestionItem.model_validate(s) for s in data.get("suggestions", [])]
        return GenerateSuggestionsResult(success=True, suggestions=items)
    except ValueError:
        return GenerateSuggestionsResult(success=False, error="Failed to generate suggestions", suggestions=MOCK)
