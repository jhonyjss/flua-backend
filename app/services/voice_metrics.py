"""Voice session metrics (Flua stage 2b): one row of counters per lesson or conversation.

The table (voice_session_metrics) lives in the flueai repo's migrations: RLS on and no policy, so only
this service-role client reads and writes it. Rows cascade from profiles on account deletion.
"""
import logging

from fastapi import HTTPException

from app.schemas.realtime import SessionMetricsRequest
from app.services import supabase_admin as db

logger = logging.getLogger(__name__)

TABLE = "voice_session_metrics"


def metrics_row(user_id: str, body: SessionMetricsRequest) -> dict:
    """The request as a table row: snake_case columns, one column per outcome."""
    return {
        "user_id": user_id,
        "session_id": str(body.sessionId),
        "client": body.client,
        "mode": body.mode,
        "language": body.language,
        "level": body.level,
        "model": body.model,
        "prompt_version": body.promptVersion,
        "lesson_id": body.lessonId,
        "duration_seconds": body.durationSeconds,
        "learner_turns": body.learnerTurns,
        "flua_turns": body.fluaTurns,
        "flua_words": body.fluaWords,
        "flua_words_max": body.fluaWordsMax,
        "opening_words": body.openingWords,
        "opening_seconds": body.openingSeconds,
        "outcome_correto": body.outcomes.correto,
        "outcome_parcial": body.outcomes.parcial,
        "outcome_incorreto": body.outcomes.incorreto,
        "outcome_fora_do_roteiro": body.outcomes.fora_do_roteiro,
        "goals_reached": body.goalsReached,
        "goals_after_misses": body.goalsAfterMisses,
        "skipped_turns": body.skippedTurns,
        "silence_nudges": body.silenceNudges,
        "unreadable_evaluations": body.unreadableEvaluations,
        "reconnects": body.reconnects,
        "ended_by": body.endedBy,
    }


async def save(user_id: str, body: SessionMetricsRequest) -> None:
    """A session sent twice keeps its first row. A failed write is logged here (the clients ignore the answer,
    so this is the only trace of lost metrics) and answered without the database's error text."""
    try:
        await db.upsert(TABLE, metrics_row(user_id, body), on_conflict="session_id", ignore_duplicates=True)
    except HTTPException as err:
        logger.warning("voice session metrics not saved (user %s): %s", user_id, err.detail)
        raise HTTPException(502, "Não foi possível gravar as métricas da sessão.") from err
