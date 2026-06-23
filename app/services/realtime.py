"""OpenAI Realtime — ephemeral client secret (parity with server/api/realtime/session.post.ts)."""
import asyncio
import logging

from fastapi import HTTPException

from app.core.auth import AuthUser
from app.core.config import get_settings
from app.core.http import http_client
from app.schemas.realtime import RealtimeSessionRequest
from app.services.tutor_instructions import build_tutor_instructions, cap_lesson_context

# GA realtime model (https://developers.openai.com/api/docs/models/gpt-realtime).
# NOT "gpt-4o-realtime-preview" (the deprecated beta — 404s with model_not_found).
# The model is bound to the ephemeral token here; the browser SDP handshake must
# NOT also pass ?model= (it would mismatch the token's resolved snapshot).
logger = logging.getLogger(__name__)

REALTIME_MODEL = "gpt-realtime"


def _turn_detection(turn_mode: str) -> dict:
    """Server VAD config by turn-taking mode.

    "educational" (default): the SERVER does NOT auto-respond and Flua is NOT
    interruptible — the client commits the turn after a validated final
    transcript and triggers the response. A long silence window (1400ms)
    tolerates learners who pause between words ("The… number… of people…")
    instead of cutting their turn early.

    "responsive": snappy auto-reply (server creates the response on ~520ms of
    silence and can be interrupted) — opt-in / future premium.
    """
    if turn_mode == "responsive":
        return {
            "type": "server_vad",
            "threshold": 0.45,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 520,
            "create_response": True,
            "interrupt_response": True,
        }
    return {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 1400,
        "create_response": False,
        "interrupt_response": False,
    }
SESSION_TIMEOUT_S = 18.0
MAX_RETRIES = 1


def _resolve_student_name(req: RealtimeSessionRequest, user: AuthUser | None) -> str:
    """The tutor's name source. Prefer the authenticated session identity (the
    JWT claim) over the client-supplied value so the name can't be spoofed or
    leaked from another context; fall back to the client value (also derived
    from the authenticated profile) and finally to empty (tutor asks the name)."""
    if user and user.name and user.name.strip():
        return user.name.strip()
    return (req.studentName or "").strip()


def build_tutor_instructions_from_request(
    req: RealtimeSessionRequest, user: AuthUser | None = None,
) -> str:
    return build_tutor_instructions(
        level=req.level,
        scenario=req.scenario,
        lesson_context=cap_lesson_context(req.lessonContext),
        student_name=_resolve_student_name(req, user),
        language=req.language,
        explanation_language=req.explanationLanguage,
        learning_goals=req.learningGoals,
        mode=req.mode,
    )


def _transcription_prompt(req: RealtimeSessionRequest, user: AuthUser | None) -> str:
    """Bias the speech-to-text toward the student's real words.

    gpt-4o-transcribe accepts a free-text prompt that nudges spelling/vocabulary
    (https://developers.openai.com/api/docs/guides/realtime-transcription). We
    do NOT set `language` (that would force one language and mistranscribe the
    other) — the learner mixes Portuguese and the target language, so we only
    hint the bilingual context + the student's name so it stops inventing words
    like "Budern" for "Podemos"."""
    target = "espanhol" if req.language == "es" else "inglês"
    name = _resolve_student_name(req, user)
    first = name.split()[0] if name else ""
    who = f", de um estudante brasileiro chamado {first}" if first else ", de um estudante brasileiro"
    return (
        f"Áudio de prática de {target}{who}. "
        f"O estudante pode falar português do Brasil ou {target}. "
        "Transcreva fielmente as palavras realmente ditas; não invente, não complete "
        "e não traduza palavras. Se o áudio estiver incerto, prefira transcrever menos a chutar."
    )


async def create_session(req: RealtimeSessionRequest, user: AuthUser | None = None) -> dict:
    """Create the ephemeral client secret; returns {clientSecret, model, instructions}."""
    settings = get_settings()
    instructions = build_tutor_instructions_from_request(req, user)

    if req.pipelineMode:
        return {"clientSecret": None, "model": None, "instructions": instructions}

    if not settings.openai_api_key:
        raise HTTPException(500, "OPENAI_API_KEY not configured")

    turn_detection = _turn_detection(req.turnMode)
    logger.info(
        "[Realtime] session config language=%s mode=%s turnMode=%s vad=%s",
        req.language, req.mode, req.turnMode, turn_detection,
    )

    session_config = {
        "type": "realtime",
        "model": REALTIME_MODEL,
        "instructions": instructions,
        "audio": {
            "input": {
                "noise_reduction": {"type": "near_field"},
                "transcription": {
                    "model": "gpt-4o-transcribe",
                    "prompt": _transcription_prompt(req, user),
                },
                # Turn-taking config depends on turnMode (see _turn_detection):
                # educational tolerates learner pauses and is client-triggered;
                # responsive is the snappy auto-reply VAD. near_field noise
                # reduction runs before VAD so background noise won't false-trigger.
                "turn_detection": turn_detection,
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
