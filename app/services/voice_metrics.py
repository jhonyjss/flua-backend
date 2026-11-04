"""Voice session metrics (Flua stage 2b): one row of counters per lesson or conversation.

The table (voice_session_metrics) lives in the flueai repo's migrations: RLS on and no policy, so only
this service-role client reads and writes it. Rows cascade from profiles on account deletion.
"""
from app.schemas.realtime import SessionMetricsRequest
from app.services import supabase_admin as db

TABLE = "voice_session_metrics"


def metrics_row(user_id: str, body: SessionMetricsRequest) -> dict:
    """The request as a table row: snake_case columns, one column per outcome."""
    return {
        "user_id": user_id,
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
    await db.insert(TABLE, metrics_row(user_id, body))
