"""Generate class — port of generate-class.post.ts."""
from app.core.config import get_settings
from app.schemas.ai import GenerateClassRequest, GenerateClassResult
from app.services.anthropic_client import complete, extract_json

SYSTEM_PROMPT = """You are an expert English curriculum designer.
Return ONLY valid JSON for a speaking class with exactly 5 topics, 4 key phrases each, 6-8 vocabulary words, 5 example sentences per topic."""


async def generate_class(req: GenerateClassRequest) -> GenerateClassResult:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return GenerateClassResult(success=False, error="Anthropic API key not configured")
    user = f"Create a speaking class about: {req.topic}\nLevel: {req.level}\nCategory: {req.category}\nLanguage: {req.language}"
    try:
        raw = await complete(SYSTEM_PROMPT, user, max_tokens=6000, temperature=0.5, model=settings.anthropic_model_sonnet)
        data = extract_json(raw)
        return GenerateClassResult(success=True, data=data)
    except ValueError as exc:
        return GenerateClassResult(success=False, error=str(exc))
