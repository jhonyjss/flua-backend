"""Flua's memory of the learner's recent mistakes, between classes.

The app records each correction (the conversation's "um pequeno ajuste" and the guided lesson's
misses); a new voice session gets the newest distinct ones, and Flua brings back at most one.
Table and trimming: flueai/supabase/migrations/20261017_learner_mistakes.sql.

Failure policy: memory is a nicety. A failed read gives Flua no memory and a failed write is
logged, never an error the learner sees.
"""
import logging

from app.schemas.users import MistakeIn
from app.services import supabase_admin as db

logger = logging.getLogger(__name__)

_TABLE = "learner_mistakes"


async def record(user_id: str, mistake: MistakeIn) -> bool:
    try:
        await db.insert(_TABLE, {"user_id": user_id, **mistake.model_dump()})
        return True
    except Exception:
        logger.warning("[LearnerMemory] could not record a mistake for %s", user_id, exc_info=True)
        return False


async def recent(user_id: str, limit: int = 3) -> list[dict]:
    """The newest mistakes with distinct tips: [{said, natural, tip}]."""
    try:
        rows = await db.select_many(
            _TABLE, {"user_id": user_id}, select="said,natural,tip", order="created_at.desc", limit=12,
        )
    except Exception:
        logger.warning("[LearnerMemory] could not read mistakes for %s", user_id, exc_info=True)
        return []
    seen: set[str] = set()
    distinct: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("said") or not row.get("natural"):
            continue
        key = (row.get("tip") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        distinct.append({"said": row["said"], "natural": row["natural"], "tip": row["tip"]})
        if len(distinct) == limit:
            break
    return distinct
