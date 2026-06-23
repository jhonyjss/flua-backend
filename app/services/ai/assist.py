"""Assist — port of assist.post.ts."""
from app.core.config import get_settings
from app.schemas.ai import AssistRequest, AssistResult
from app.services.anthropic_client import complete

SYSTEM_PROMPTS = {
    "improve": "Improve the text to be more engaging and clear. Return ONLY the improved text.",
    "expand": "Expand the text with more detail. Return ONLY the expanded text.",
    "translate": "Translate accurately. Return ONLY the translated text.",
    "suggest": "Suggest appropriate content for the field. Return ONLY the suggestion.",
    "simplify": "Simplify for language learners A2-B1. Return ONLY the simplified text.",
    "respond": "Reply in character. Return ONLY the in-character reply.",
}


async def assist(req: AssistRequest) -> AssistResult:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return AssistResult(success=False, error="Anthropic API key not configured")
    system = SYSTEM_PROMPTS.get(req.action)
    if not system:
        return AssistResult(success=False, error="Invalid action")
    user = req.text
    if req.action == "translate" and req.targetLanguage:
        user = f"Translate to {req.targetLanguage}:\n\n{req.text}"
    elif req.action == "suggest" and req.context and req.field:
        user = f"Context: {req.context}\n\nSuggest content for the \"{req.field}\" field."
    try:
        result = await complete(system, user, max_tokens=1024, temperature=0.4)
        return AssistResult(success=True, result=result.strip())
    except Exception as exc:
        return AssistResult(success=False, error=str(exc))
