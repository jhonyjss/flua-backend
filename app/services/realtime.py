"""OpenAI Realtime — ephemeral client secret (parity with server/api/realtime/session.post.ts).

Key decisions ported from the Nuxt endpoint:
- model `gpt-realtime` (GA), minted via /v1/realtime/client_secrets
- near_field noise reduction BEFORE VAD (kills ghost messages)
- semantic_vad with interrupt_response for natural turn-taking
- lesson context hard-capped at 4000 chars
- 18s timeout + 1 retry on 5xx
"""
import asyncio

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client
from app.schemas.realtime import RealtimeSessionRequest

REALTIME_MODEL = "gpt-realtime"
SESSION_TIMEOUT_S = 18.0
MAX_RETRIES = 1
LESSON_CONTEXT_CAP = 4000


def cap_lesson_context(context: str, cap: int = LESSON_CONTEXT_CAP) -> str:
    return context[:cap]


def build_tutor_instructions(req: RealtimeSessionRequest) -> str:
    """Tutor system prompt. Ported summary of server/utils/prompts/tutorInstructions."""
    target = "Spanish" if req.language == "es" else "English"
    name = req.studentName.strip()
    greet = f'Greet the student by name ("{name}") warmly, in one sentence.' if name else (
        "Greet the student warmly and ask their name."
    )
    level_style = {
        "beginner": "Speak slowly. Use Portuguese for explanations and the target language for practice.",
        "intermediate": f"Speak mostly {target}, switching to Portuguese only when the student is lost.",
        "advanced": f"Speak only {target}, at natural speed.",
    }[req.level]
    context = cap_lesson_context(req.lessonContext)
    return "\n".join(filter(None, [
        f"You are Flua, a warm, encouraging {target} tutor for Brazilian students.",
        level_style,
        f"Scenario: {req.scenario}.",
        greet,
        "Teach ONE point at a time; have the student produce or repeat; correct gently. "
        'When they get it right, start with "Correct!", praise them, and move on. Keep every turn short (1-3 sentences).',
        f"Lesson context:\n{context}" if context else "",
    ]))


async def create_session(req: RealtimeSessionRequest) -> dict:
    """Create the ephemeral client secret; returns {clientSecret, model, instructions}."""
    settings = get_settings()
    instructions = build_tutor_instructions(req)

    if req.pipelineMode:
        return {"clientSecret": None, "model": None, "instructions": instructions}

    if not settings.openai_api_key:
        raise HTTPException(500, "OPENAI_API_KEY not configured")

    session_config = {
        "type": "realtime",
        "model": REALTIME_MODEL,
        "instructions": instructions,
        "audio": {
            "input": {
                "noise_reduction": {"type": "near_field"},
                "transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "semantic_vad",
                    "eagerness": "auto",
                    "interrupt_response": True,
                },
            },
            "output": {"voice": req.voice},
        },
    }

    last_error = "unknown"
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with http_client(timeout=SESSION_TIMEOUT_S) as client:
                res = await client.post(
                    "https://api.openai.com/v1/realtime/client_secrets",
                    json={"session": session_config},
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                )
        except Exception as err:  # timeout / network
            last_error = str(err)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            raise HTTPException(504, f"OpenAI Realtime timeout: {last_error[:200]}") from err

        if res.status_code >= 500 and attempt < MAX_RETRIES:
            last_error = res.text[:200]
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        if res.status_code != 200:
            raise HTTPException(502, f"OpenAI Realtime error {res.status_code}: {res.text[:200]}")

        data = res.json()
        secret = data.get("value") or (data.get("client_secret") or {}).get("value")
        if not secret:
            raise HTTPException(502, "OpenAI did not return a client secret")
        return {"clientSecret": secret, "model": REALTIME_MODEL, "instructions": instructions}

    raise HTTPException(502, f"OpenAI Realtime failed after retries: {last_error}")
