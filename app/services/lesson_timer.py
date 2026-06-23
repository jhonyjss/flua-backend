"""Server-enforced per-lesson time budget.

The free plan gets 5 minutes per lesson and paid plans 15 minutes. The server
is the source of truth (consumed seconds persisted per user+lesson), so the
limit holds across devices — the client only displays a countdown and sends
periodic heartbeats.

Design choices:
- Limit is recomputed from the live subscription on every call (a plan upgrade
  takes effect immediately).
- Fails OPEN: if the subscription or the usage table can't be read, we return a
  permissive status (paid limit, no expiry) so an infra hiccup never locks a
  student — especially a paying one — out of a lesson.
- Heartbeat deltas are clamped so a tampered client can't burn the budget
  instantly or run it backwards.
"""
from datetime import datetime, timezone

from app.services import supabase_admin as db
from app.services.user_data import get_subscription

FREE_LIMIT_SECONDS = 5 * 60
PAID_LIMIT_SECONDS = 15 * 60
# Heartbeats run ~every 15s; allow some slack for tab-throttling/retries but
# never more than this per call so a forged delta can't drain the budget.
MAX_HEARTBEAT_DELTA = 90

_TABLE = "lesson_time_usage"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status(limit: int, consumed: int) -> dict:
    consumed = max(0, consumed)
    return {
        "limitSeconds": limit,
        "consumedSeconds": consumed,
        "remainingSeconds": max(0, limit - consumed),
        "expired": consumed >= limit,
    }


async def limit_for_user(user_id: str) -> int:
    """Per-lesson budget in seconds for this user's current plan."""
    try:
        sub = await get_subscription(user_id)
        return PAID_LIMIT_SECONDS if sub.isSubscribed else FREE_LIMIT_SECONDS
    except Exception:
        return PAID_LIMIT_SECONDS  # fail open — never lock a (paying) user out


async def get_status(user_id: str, lesson_id: str) -> dict:
    limit = await limit_for_user(user_id)
    try:
        row = await db.select_one(_TABLE, {"user_id": user_id, "lesson_id": lesson_id})
    except Exception:
        return _status(limit, 0)  # table missing / unreachable → fail open
    consumed = int((row or {}).get("consumed_seconds") or 0)
    return _status(limit, consumed)


async def add_time(user_id: str, lesson_id: str, delta_seconds: int) -> dict:
    """Accumulate consumed time for (user, lesson) and return the new status."""
    limit = await limit_for_user(user_id)
    delta = max(0, min(int(delta_seconds or 0), MAX_HEARTBEAT_DELTA))
    try:
        row = await db.select_one(_TABLE, {"user_id": user_id, "lesson_id": lesson_id})
        current = int((row or {}).get("consumed_seconds") or 0)
        new_consumed = current + delta
        if row:
            await db.update(_TABLE, {"id": str(row["id"])}, {
                "consumed_seconds": new_consumed,
                "limit_seconds": limit,
                "updated_at": _now_iso(),
            })
        else:
            await db.insert(_TABLE, {
                "user_id": user_id,
                "lesson_id": lesson_id,
                "consumed_seconds": new_consumed,
                "limit_seconds": limit,
            })
        return _status(limit, new_consumed)
    except Exception:
        return _status(limit, 0)  # fail open


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
