"""Server-enforced free-conversation credit pool (Flua "conversa livre").

A PERIODIC pool (not per-session), by plan:
  free    → 5 minutes per calendar WEEK
  starter → 90 minutes per calendar MONTH
  pro     → 180 minutes per calendar MONTH
  premium → 180 minutes per calendar MONTH

The limit and the period are recomputed from the live subscription on every
call, so a plan upgrade takes effect immediately and each new calendar period
auto-resets (a new period_key simply has no row yet). One row per
(user, period_key) accumulates consumed seconds.

Design (parity with lesson_timer):
- Fails OPEN: if the subscription or the usage table can't be read, return a
  permissive status (paid limit, no expiry) so an infra hiccup never wrongly
  blocks a user — especially a paying one.
- Heartbeat deltas are clamped so a tampered client can't drain the pool
  instantly or run it backwards.
"""
from datetime import datetime, timezone

from app.services import supabase_admin as db
from app.services.user_data import get_subscription

WEEK_SECONDS_FREE = 5 * 60
MONTH_SECONDS_STARTER = 90 * 60
MONTH_SECONDS_PRO = 180 * 60
MONTH_SECONDS_PREMIUM = 180 * 60

# Heartbeats run ~every 15s; allow slack for tab-throttling/retries but never
# more than this per call so a forged delta can't drain the pool.
MAX_HEARTBEAT_DELTA = 90

_TABLE = "conversation_credits"

_LIMITS = {
    "free": WEEK_SECONDS_FREE,
    "starter": MONTH_SECONDS_STARTER,
    "pro": MONTH_SECONDS_PRO,
    "premium": MONTH_SECONDS_PREMIUM,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_plan(plan_level: str | None, is_subscribed: bool) -> str:
    """Normalize a (possibly suffixed) plan level to a base tier.

    Handles "starter_monthly", "pro_yearly", etc. A non-subscribed or unknown
    user is "free"; any other active paid plan falls back to at least "starter".
    """
    if not is_subscribed or not plan_level:
        return "free"
    p = plan_level.lower()
    if p.startswith("pro"):
        return "pro"
    if p.startswith("premium"):
        return "premium"
    if p.startswith("starter"):
        return "starter"
    return "starter"


def _period_key(plan: str, now: datetime) -> str:
    """free → ISO week ("2026-W24"); paid → calendar month ("2026-06")."""
    if plan == "free":
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    return f"{now.year}-{now.month:02d}"


def _period_label(plan: str) -> str:
    return "semana" if plan == "free" else "mês"


def _status(plan: str, limit: int, consumed: int) -> dict:
    consumed = max(0, consumed)
    return {
        "limitSeconds": limit,
        "consumedSeconds": consumed,
        "remainingSeconds": max(0, limit - consumed),
        "expired": consumed >= limit,
        "planLevel": plan,
        "isFree": plan == "free",
        "periodLabel": _period_label(plan),
    }


async def _plan_state(user_id: str) -> tuple[str, int, str]:
    """(base_plan, limit_seconds, period_key) for the user's current plan."""
    now = datetime.now(timezone.utc)
    try:
        sub = await get_subscription(user_id)
        plan = _base_plan(sub.planLevel, sub.isSubscribed)
    except Exception:
        plan = "pro"  # fail open — treat as a generous paid plan
    return plan, _LIMITS.get(plan, WEEK_SECONDS_FREE), _period_key(plan, now)


async def get_status(user_id: str) -> dict:
    plan, limit, period_key = await _plan_state(user_id)
    try:
        row = await db.select_one(_TABLE, {"user_id": user_id, "period_key": period_key})
    except Exception:
        return _status(plan, limit, 0)  # table missing / unreachable → fail open
    consumed = int((row or {}).get("consumed_seconds") or 0)
    return _status(plan, limit, consumed)


async def add_time(user_id: str, delta_seconds: int) -> dict:
    """Accumulate consumed conversation time for the current period."""
    plan, limit, period_key = await _plan_state(user_id)
    delta = max(0, min(int(delta_seconds or 0), MAX_HEARTBEAT_DELTA))
    try:
        row = await db.select_one(_TABLE, {"user_id": user_id, "period_key": period_key})
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
                "period_key": period_key,
                "consumed_seconds": new_consumed,
                "limit_seconds": limit,
            })
        return _status(plan, limit, new_consumed)
    except Exception:
        return _status(plan, limit, 0)  # fail open
