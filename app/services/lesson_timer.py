"""Server-enforced per-lesson time budget.

Every lesson with Flua gets 10 minutes, free trial or paid (owner decision 2026-11-12; paid was 15).
For subscribers the lesson also spends the month's pool (voice_minutes: 60 min Starter, 120 min Pro),
and the status merges both: remainingSeconds is the smaller of the two, and expiredReason says which
ran out. The server is the source of truth (consumed seconds persisted per user+lesson), so the limit
holds across devices — the client only displays a countdown and sends periodic heartbeats.

Design choices:
- Fails OPEN: if the usage table or the pool can't be read, we return a permissive status so an
  infra hiccup never locks a student — especially a paying one — out of a lesson.
- Heartbeat deltas are clamped so a tampered client can't burn the budget instantly or run it
  backwards.
"""
import asyncio
from datetime import datetime, timezone

from app.services import supabase_admin as db
from app.services import voice_minutes

LESSON_LIMIT_SECONDS = 10 * 60
# Heartbeats run ~every 15s; allow some slack for tab-throttling/retries but
# never more than this per call so a forged delta can't drain the budget.
MAX_HEARTBEAT_DELTA = 90

_TABLE = "lesson_time_usage"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status(consumed: int, pool: dict) -> dict:
    """The lesson's budget merged with the month's pool (when the pool applies to the account)."""
    limit = LESSON_LIMIT_SECONDS
    consumed = max(0, consumed)
    unlimited = bool(pool.get("isUnlimited"))
    remaining = limit if unlimited else max(0, limit - consumed)
    reason = None
    if not unlimited and consumed >= limit:
        reason = "lesson"
    monthly_limit = monthly_remaining = None
    if pool.get("applies"):
        monthly_limit = pool["limitSeconds"]
        monthly_remaining = pool["remainingSeconds"]
        remaining = min(remaining, monthly_remaining)
        # The month wins a tie: it also closes the next lesson, which is what the learner needs to know.
        if pool["expired"]:
            reason = "month"
    return {
        "limitSeconds": limit,
        "consumedSeconds": consumed,
        "remainingSeconds": remaining,
        "expired": reason is not None,
        "isUnlimited": unlimited,
        "monthlyLimitSeconds": monthly_limit,
        "monthlyRemainingSeconds": monthly_remaining,
        "expiredReason": reason,
    }


async def _lesson_consumed(user_id: str, lesson_id: str) -> int:
    try:
        row = await db.select_one(_TABLE, {"user_id": user_id, "lesson_id": lesson_id})
    except Exception:
        return 0  # table missing / unreachable → fail open
    return int((row or {}).get("consumed_seconds") or 0)


async def get_status(user_id: str, lesson_id: str) -> dict:
    pool, consumed = await asyncio.gather(
        voice_minutes.get_status(user_id), _lesson_consumed(user_id, lesson_id),
    )
    return _status(consumed, pool)


async def _add_to_lesson(user_id: str, lesson_id: str, delta: int) -> int:
    """The lesson's consumed seconds after this beat; what was stored before it if the write fails."""
    current = 0
    try:
        row = await db.select_one(_TABLE, {"user_id": user_id, "lesson_id": lesson_id})
        current = int((row or {}).get("consumed_seconds") or 0)
        if row:
            await db.update(_TABLE, {"id": str(row["id"])}, {
                "consumed_seconds": current + delta,
                "limit_seconds": LESSON_LIMIT_SECONDS,
                "updated_at": _now_iso(),
            })
        else:
            await db.insert(_TABLE, {
                "user_id": user_id,
                "lesson_id": lesson_id,
                "consumed_seconds": current + delta,
                "limit_seconds": LESSON_LIMIT_SECONDS,
            })
        return current + delta
    except Exception:
        return current  # fail open, without pretending the lesson starts over


async def add_time(user_id: str, lesson_id: str, delta_seconds: int) -> dict:
    """Accumulate consumed time for (user, lesson), then spend the same seconds of the month's pool,
    and return the merged status."""
    delta = max(0, min(int(delta_seconds or 0), MAX_HEARTBEAT_DELTA))
    consumed = await _add_to_lesson(user_id, lesson_id, delta)
    pool = await voice_minutes.add_time(user_id, delta)
    return _status(consumed, pool)


async def add_activity(user_id: str, lesson_id: str, delta_seconds: int) -> int:
    """Record time spent in a lesson WITHOUT touching its budget, and return the lesson's total.

    For learners the client does not count down for (admins; Pro on site builds from before
    2026-11-12, which still call this), so the admin still sees how long they studied. A
    subscriber's seconds still spend the month's pool here, so an old client can't get around it.
    Budget heartbeats need no call here: the database adds every increase of consumed_seconds to
    active_seconds (migration 20261106_lesson_time_active_seconds).
    Raises on a storage error so the client keeps the seconds and sends them again.
    """
    delta = max(0, min(int(delta_seconds or 0), MAX_HEARTBEAT_DELTA))
    row = await db.select_one(_TABLE, {"user_id": user_id, "lesson_id": lesson_id})
    active = int((row or {}).get("active_seconds") or 0) + delta
    if delta == 0:
        return active
    if row:
        await db.update(_TABLE, {"id": str(row["id"])}, {
            "active_seconds": active,
            "updated_at": _now_iso(),
        })
    else:
        await db.insert(_TABLE, {
            "user_id": user_id,
            "lesson_id": lesson_id,
            "consumed_seconds": 0,
            "active_seconds": active,
            "limit_seconds": LESSON_LIMIT_SECONDS,
        })
    # Spent only once the lesson row is saved: a 503 above makes the client resend these seconds.
    await voice_minutes.add_time(user_id, delta)  # fails open on its own
    return active


async def reset(user_id: str, lesson_id: str) -> None:
    """Clear the budget for a lesson (e.g. when an admin grants a retry)."""
    try:
        row = await db.select_one(_TABLE, {"user_id": user_id, "lesson_id": lesson_id})
        if row:
            await db.update(_TABLE, {"id": str(row["id"])}, {
                "consumed_seconds": 0,
                "updated_at": _now_iso(),
            })
    except Exception:
        pass
