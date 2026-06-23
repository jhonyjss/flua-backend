"""Dynamic examples — port of dynamic-examples.post.ts."""
from app.core.config import get_settings
from app.schemas.ai import DynamicExampleItem, DynamicExamplesRequest, DynamicExamplesResult
from app.services.anthropic_client import complete, extract_json

FALLBACK = [
    DynamicExampleItem(english="I am happy today.", portuguese="Estou feliz hoje.", context="daily life", difficulty="beginner"),
    DynamicExampleItem(english="She is a teacher.", portuguese="Ela é professora.", context="introductions", difficulty="beginner"),
]


async def dynamic_examples(req: DynamicExamplesRequest) -> DynamicExamplesResult:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return DynamicExamplesResult(examples=FALLBACK[: req.count], teachingTip="Practice aloud.")

    system = """Generate bilingual example sentences for an English lesson.
Return JSON: {"examples":[{"english":str,"portuguese":str,"context":str,"difficulty":str,"vocabularyUsed":[str],"grammarPointUsed":str}],"teachingTip":str}"""
    user = (
        f"Topic: {req.topic} ({req.topicPt})\nLevel: {req.level}\n"
        f"Vocabulary: {', '.join(req.vocabularyWords)}\nGrammar: {req.grammarPoint}\n"
        f"Key phrases: {', '.join(req.keyPhrases)}\nCount: {req.count}"
    )
    try:
        raw = await complete(system, user, max_tokens=900, temperature=0.5, model=settings.anthropic_model_haiku)
        data = extract_json(raw)
        examples = [DynamicExampleItem.model_validate(e) for e in data.get("examples", [])]
        return DynamicExamplesResult(examples=examples, teachingTip=data.get("teachingTip"))
    except ValueError:
        return DynamicExamplesResult(examples=FALLBACK)
