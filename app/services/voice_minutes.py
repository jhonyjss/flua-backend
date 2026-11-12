"""Monthly pool of Flua voice minutes for subscribers (owner decision, 2026-11-12).

  starter         → 60 minutes per calendar month
  pro / premium   → 120 minutes per calendar month
  free            → the pool does not apply: free accounts only get their trial lessons, which
                    keep their own 10-minute budget (lesson_timer) and never touch the pool
  admin           → unlimited

Lessons with Flua spend the pool through lesson_timer's heartbeats (and the site's activity beats),
so a lesson stops when either its 10 minutes or the month's minutes run out. The month is the
calendar month in America/Sao_Paulo, where the learners are.

Storage: the conversation_credits table, unique on (user_id, period_key), with a "YYYY-MM" key.
Free conversation used that table with day ("2026-11-12") and ISO-week ("2026-W46") keys and was
removed from every plan on the same date, so a month key never meets one of its rows. Seconds are
added by add_voice_seconds (flueai migration 20261112_voice_minutes_lock), one atomic upsert, so
two devices or a doubled flush can't lose a beat; the same migration takes writes away from
signed-in users, who could otherwise reset their own month through PostgREST.

Fails OPEN like lesson_timer: an unreadable subscription or table never blocks a lesson. Every
fail-open is logged, since a silent one would lift the cap for everyone.
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services import supabase_admin as db
from app.services.conversation_credits import _base_plan, is_admin
from app.services.user_data import get_subscription

MONTH_SECONDS = {
    "starter": 60 * 60,
    "pro": 120 * 60,
    "premium": 120 * 60,
}
# Heartbeats run ~every 15 s; the same clamp as lesson_timer so a forged delta can't drain the pool.
MAX_HEARTBEAT_DELTA = 90

_TABLE = "conversation_credits"
_ADD_FN = "add_voice_seconds"
_TZ = ZoneInfo("America/Sao_Paulo")

logger = logging.getLogger(__name__)


def period_key(now: datetime | None = None) -> str:
    return (now or datetime.now(_TZ)).astimezone(_TZ).strftime("%Y-%m")


def _status(plan: str, limit: int, consumed: int, key: str, *, applies: bool, unlimited: bool = False) -> dict:
    consumed = max(0, consumed)
    return {
        "limitSeconds": limit,
        "consumedSeconds": consumed,
        "remainingSeconds": max(0, limit - consumed),
        "expired": applies and consumed >= limit,
        "planLevel": plan,
        "isUnlimited": unlimited,
        "periodKey": key,
        # Internal: whether the pool limits this account (subscribers only). Not in the API model.
        "applies": applies,
    }


async def _plan(user_id: str) -> tuple[str, bool, bool]:
    """(base_plan, applies, unlimited)."""
    if await is_admin(user_id):
        return "admin", False, True
    try:
        sub = await get_subscription(user_id)
    except Exception as err:
        logger.warning("voice minutes: plan unreadable, failing open (%s)", type(err).__name__)
        return "unknown", False, False  # fail open: an unreadable plan never blocks a lesson
    plan = _base_plan(sub.planLevel, sub.isSubscribed)
    return plan, plan in MONTH_SECONDS, False


async def _row(user_id: str, key: str) -> dict | None:
    return await db.select_one(_TABLE, {"user_id": user_id, "period_key": key})


async def _stored(user_id: str, key: str) -> int:
    row = await _row(user_id, key)
    return int((row or {}).get("consumed_seconds") or 0)


async def get_status(user_id: str) -> dict:
    key = period_key()
    plan, applies, unlimited = await _plan(user_id)
    limit = MONTH_SECONDS.get(plan, 0)
    if not applies:
        return _status(plan, limit, 0, key, applies=False, unlimited=unlimited)
    try:
        return _status(plan, limit, await _stored(user_id, key), key, applies=True)
    except Exception as err:
        logger.warning("voice minutes: pool unreadable, failing open (%s)", type(err).__name__)
        return _status(plan, limit, 0, key, applies=True)


async def _add_by_hand(user_id: str, key: str, delta: int, limit: int) -> int:
    """Read, add and write: not atomic, but keeps the cap when add_voice_seconds is missing (a deploy
    before the flueai migration) or failing. Concurrent beats can lose a few seconds here."""
    row = await _row(user_id, key)
    consumed = int((row or {}).get("consumed_seconds") or 0) + delta
    if row:
        await db.update(_TABLE, {"id": str(row["id"])}, {
            "consumed_seconds": consumed,
            "limit_seconds": limit,
            "updated_at": datetime.now(_TZ).isoformat(),
        })
    else:
        await db.insert(_TABLE, {"user_id": user_id, "period_key": key, "consumed_seconds": consumed, "limit_seconds": limit})
    return consumed


async def add_time(user_id: str, delta_seconds: int) -> dict:
    """Spend seconds of the month's pool; a no-op for accounts the pool doesn't apply to."""
    key = period_key()
    plan, applies, unlimited = await _plan(user_id)
    limit = MONTH_SECONDS.get(plan, 0)
    if not applies:
        return _status(plan, limit, 0, key, applies=False, unlimited=unlimited)
    delta = max(0, min(int(delta_seconds or 0), MAX_HEARTBEAT_DELTA))
    try:
        if delta == 0:
            return _status(plan, limit, await _stored(user_id, key), key, applies=True)
        consumed = await db.rpc(_ADD_FN, {"p_user_id": user_id, "p_period_key": key, "p_delta": delta, "p_limit": limit})
        return _status(plan, limit, int(consumed), key, applies=True)
    except Exception as err:
        logger.warning("voice minutes: atomic add failed, adding by hand (%s)", type(err).__name__)
    try:
        return _status(plan, limit, await _add_by_hand(user_id, key, delta, limit), key, applies=True)
    except Exception as err:
        logger.warning("voice minutes: %ss not added, failing open (%s)", delta, type(err).__name__)
        return _status(plan, limit, 0, key, applies=True)
