"""Flua "conversa livre" (free conversation): removed from every plan on 2026-11-12 (owner decision).

Only admins (profiles.role = 'admin') still converse, without limit. Everyone else gets a locked
status, so clients built before the removal show the conversation as unavailable and
POST /api/realtime/session refuses free_practice. Subscribers' voice time is now the monthly pool of
lessons with Flua (voice_minutes), which reuses this module's table.

is_admin and _base_plan stay here: lesson_timer, voice_minutes and the classroom import them.
"""
from app.services import supabase_admin as db
from app.services.user_data import get_subscription


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


async def is_admin(user_id: str) -> bool:
    """Admins (profiles.role = 'admin') get the conversation unlimited, the server-side twin of the
    site's isAdmin bypass in useLessonAccess. Fails CLOSED: an unreadable profile is not an admin."""
    try:
        row = await db.select_one("profiles", {"id": user_id})
        return (row or {}).get("role") == "admin"
    except Exception:
        return False


def _status(plan: str, *, unlimited: bool) -> dict:
    return {
        "limitSeconds": 0,
        "consumedSeconds": 0,
        "remainingSeconds": 0,
        "expired": not unlimited,
        "planLevel": plan,
        "isFree": plan == "free",
        "isUnlimited": unlimited,
        "periodLabel": "livre" if unlimited else "indisponível",
    }


def can_converse(status: dict) -> bool:
    """Whether a status allows starting a free conversation: only an admin's (unlimited) one now."""
    return bool(status.get("isUnlimited"))


async def get_status(user_id: str) -> dict:
    if await is_admin(user_id):
        return _status("premium", unlimited=True)
    try:
        sub = await get_subscription(user_id)
        plan = _base_plan(sub.planLevel, sub.isSubscribed)
    except Exception:
        plan = "free"  # the answer is "locked" either way
    return _status(plan, unlimited=False)


async def add_time(user_id: str, delta_seconds: int) -> dict:
    """Nothing to spend: kept so old clients' heartbeats get a status back instead of a 404."""
    return await get_status(user_id)
