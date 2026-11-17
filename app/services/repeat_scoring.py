"""POST /api/ai/score-repeat — a sentence the learner said in a route event, scored on the server
(flueai-app docs/rotas/02-progresso-e-fala-no-backend.md; rotas-com-a-flua.md §4).

Deepgram nova-2 transcribes; the score is 1 − WER (src/speech/scorer.py) against the best accepted
variation. Low confidence is "não ouvi bem", never a fail. Every score is kept for calibrating the
thresholds — transcript and score only, never the audio (route_speech_scores).
"""
import logging
from typing import Literal

from app.schemas.ai import TranscribeResult
from app.services import speech_correction  # noqa: F401 — puts src/ on the path for `speech`
from app.services import stt
from app.services import supabase_admin as db
from speech.normalizer import tokenize
from speech.scorer import score_transcription

logger = logging.getLogger(__name__)

Status = Literal["correct", "almost", "retry", "unheard"]

# Initial thresholds of the proposal, to calibrate with route_speech_scores before opening to everyone.
CORRECT = 0.80
CORRECT_SHORT = 0.70  # sentences of up to 3 words: one slip is a third of them
SHORT_WORDS = 3
ALMOST = 0.50
LOW_CONFIDENCE = 0.55


def verdict(phrase: str, accepts: list[str], transcript: str, confidence: float | None) -> dict:
    """Status, accuracy and missing words of the best variation (pure; the route below adds STT)."""
    if not transcript.strip():
        return {"status": "unheard", "accuracy": 0.0, "missing_words": []}
    best = None
    best_words = 0
    for reference in dict.fromkeys([phrase, *accepts]):
        result = score_transcription(reference, transcript)
        if best is None or result.accuracy > best.accuracy:
            best, best_words = result, len(tokenize(reference))
    accuracy = round(best.accuracy, 3)
    threshold = CORRECT_SHORT if best_words <= SHORT_WORDS else CORRECT
    status: Status
    if accuracy >= threshold:
        status = "correct"
    elif confidence is not None and confidence < LOW_CONFIDENCE:
        status = "unheard"
    elif accuracy >= ALMOST:
        status = "almost"
    else:
        status = "retry"
    return {"status": status, "accuracy": accuracy, "missing_words": [] if status == "correct" else best.missing_words}


async def score_repeat(
    user_id: str,
    audio: bytes,
    content_type: str,
    phrase: str,
    accepts: list[str],
    event_id: str | None,
    item_id: str | None,
) -> dict:
    heard: TranscribeResult = await stt.transcribe_file(audio, content_type, "en")
    transcript = heard.transcript.strip()
    scored = verdict(phrase, accepts, transcript, heard.confidence)
    try:
        await db.insert("route_speech_scores", {
            "user_id": user_id,
            "event_id": event_id,
            "item_id": item_id,
            "phrase": phrase,
            "transcript": transcript,
            "accuracy": scored["accuracy"],
            "confidence": None if heard.confidence is None else round(heard.confidence, 3),
            "status": scored["status"],
        })
    except Exception:  # calibration data never costs the learner the answer
        logger.warning("route_speech_scores insert failed", exc_info=True)
    return {**scored, "transcript": transcript}
