"""Generate room — port of generate-room.post.ts."""
from app.core.config import get_settings
from app.schemas.ai import GenerateRoomRequest, GenerateRoomResult
from app.services.anthropic_client import complete, extract_json

SYSTEM_PROMPT = """You are an expert at designing English-learning escape room scenarios.
Return ONLY valid JSON with keys: room, scene, vocabulary, grammar, puzzles."""


async def generate_room(req: GenerateRoomRequest) -> GenerateRoomResult:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return GenerateRoomResult(success=False, error="Anthropic API key not configured")
    user = f"Prompt: {req.prompt}\nDifficulty: {req.difficulty}\nCategory: {req.category}"
    try:
        raw = await complete(SYSTEM_PROMPT, user, max_tokens=8000, temperature=0.6, model=settings.anthropic_model_sonnet)
        data = extract_json(raw)
        return GenerateRoomResult(success=True, data=data)
    except ValueError as exc:
        return GenerateRoomResult(success=False, error=str(exc))
