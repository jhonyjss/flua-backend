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
# The actual model/transcription/noise-reduction are read from settings
# (env-overridable) — see app/core/config.py. This constant is only a fallback.
logger = logging.getLogger(__name__)

REALTIME_MODEL = "gpt-realtime-2"


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
        # 1400ms (not the playground's 500ms default) is deliberate: educational
        # mode is client-triggered and must tolerate learners who pause between
        # words. A short window would finalize the transcript mid-sentence and
        # cut them off. See tests/test_realtime.py (silence >= 1200).
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
        topic=req.topic,
        guided=req.plan.model_dump() if req.plan else None,
        resume_from_item=req.resumeFromItem,
    )


# Guided lesson: Flua reports every evaluation here instead of the app reading her
# captions. The app forces it per response (tool_choice on response.create) after
# each learner attempt and answers with the next step (flueai-app docs/aula-guiada-spec.md).
GUIDED_LESSON_TOOL = {
    "type": "function",
    "name": "registrar_resultado",
    "description": "Registra a avaliação da última fala do aluno na etapa atual da aula guiada.",
    "parameters": {
        "type": "object",
        "properties": {
            "item_id": {"type": "string", "description": "O id do item atual, como no plano da aula."},
            "etapa": {"type": "string", "enum": ["repetir", "sozinho"]},
            "resultado": {"type": "string", "enum": ["correto", "parcial", "incorreto", "fora_do_roteiro"]},
            "o_que_ouviu": {"type": "string", "description": "A frase do aluno, como foi transcrita."},
            "forma_correta": {"type": "string", "description": "A frase certa, quando o resultado não for correto."},
        },
        "required": ["item_id", "etapa", "resultado", "o_que_ouviu"],
    },
}


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


# Transcription models that accept a biasing `prompt`. gpt-realtime-whisper does
# NOT — passing `prompt` to it 400s ("prompt parameter is not supported"), which
# would break the whole session. Anything else falls back to a prompt-less config.
_PROMPT_CAPABLE_TRANSCRIBE = {"gpt-4o-transcribe", "gpt-4o-mini-transcribe", "whisper-1"}


def _transcription_config(req: RealtimeSessionRequest, user: AuthUser | None, model: str) -> dict:
    cfg: dict = {"model": model}
    if model in _PROMPT_CAPABLE_TRANSCRIBE:
        cfg["prompt"] = _transcription_prompt(req, user)
    return cfg


async def create_session(req: RealtimeSessionRequest, user: AuthUser | None = None) -> dict:
    """Create the ephemeral client secret; returns {clientSecret, model, instructions}."""
    settings = get_settings()
    instructions = build_tutor_instructions_from_request(req, user)

    if req.pipelineMode:
        return {"clientSecret": None, "model": None, "instructions": instructions}

    if not settings.openai_api_key:
        raise HTTPException(500, "OPENAI_API_KEY not configured")

    model = settings.openai_realtime_model or REALTIME_MODEL
    turn_detection = _turn_detection(req.turnMode)
    logger.info(
        "[Realtime] session config model=%s language=%s mode=%s turnMode=%s vad=%s",
        model, req.language, req.mode, req.turnMode, turn_detection,
    )

    session_config = {
        "type": "realtime",
        "model": model,
        "instructions": instructions,
        "audio": {
            "input": {
                "noise_reduction": {"type": settings.openai_realtime_noise_reduction},
                "transcription": _transcription_config(
                    req, user, settings.openai_realtime_transcribe_model,
                ),
                # Turn-taking config depends on turnMode (see _turn_detection):
                # educational tolerates learner pauses and is client-triggered;
                # responsive is the snappy auto-reply VAD. near_field noise
                # reduction runs before VAD so background noise won't false-trigger.
                "turn_detection": turn_detection,
            },
            "output": {"voice": req.voice},
        },
    }
    if req.mode == "guided_lesson":
        session_config["tools"] = [GUIDED_LESSON_TOOL]
        session_config["tool_choice"] = "auto"

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
            logger.warning("realtime session timeout after retries: %s", last_error)
            raise HTTPException(504, "O serviço de voz está temporariamente indisponível. Tente novamente.") from err

        if res.status_code >= 500 and attempt < MAX_RETRIES:
            last_error = res.text[:200]
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        if res.status_code != 200:
            logger.warning("realtime upstream error %s: %s", res.status_code, res.text[:200])
            raise HTTPException(502, "O serviço de voz retornou um erro. Tente novamente em instantes.")

        data = res.json()
        secret = data.get("value") or (data.get("client_secret") or {}).get("value")
        if not secret:
            raise HTTPException(502, "OpenAI did not return a client secret")
        return {"clientSecret": secret, "model": model, "instructions": instructions}

    logger.warning("realtime session failed after retries: %s", last_error)
    raise HTTPException(502, "O serviço de voz falhou após várias tentativas. Tente novamente.")
