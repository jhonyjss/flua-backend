"""Who may start a guided voice lesson ("Aula com a Flua" in the app).

Subscribers and admins: always. A non-subscriber gets ONE trial lesson per
account: the first lesson they start becomes the trial, they may resume that
same lesson, and any other lesson is refused. The claim is atomic in SQL
(claim_guided_lesson_trial, flueai/supabase/migrations/20261014_guided_lesson_trials.sql),
so two simultaneous starts can never win two trials.

Failure policy:
- An unreadable subscription fails OPEN (treated as a subscriber), like
  lesson_timer and conversation_credits: an infra hiccup never locks a paying
  student out.
- An unreadable or unwritable trial fails CLOSED for a known non-subscriber:
  no free lesson on an error.
"""
from dataclasses import dataclass
from typing import Literal

from app.services import supabase_admin as db
from app.services.conversation_credits import is_admin
from app.services.user_data import get_subscription

Reason = Literal["subscriber", "trial_available", "trial_in_progress", "trial_used", "unavailable"]

_TABLE = "guided_lesson_trials"
_CLAIM_FN = "claim_guided_lesson_trial"


@dataclass(frozen=True)
class GuidedAccess:
    can_start: bool
    reason: Reason
    trial_lesson_id: str | None = None
    is_admin: bool = False


async def _is_subscriber(user_id: str) -> bool:
    try:
        return (await get_subscription(user_id)).isSubscribed
    except Exception:
        return True  # fail open, as the other budgets do


async def _entitled(user_id: str) -> GuidedAccess | None:
    """Admins and subscribers, who never touch the trial; None for everyone else."""
    if await is_admin(user_id):
        return GuidedAccess(True, "subscriber", is_admin=True)
    if await _is_subscriber(user_id):
        return GuidedAccess(True, "subscriber")
    return None


def _trial_answer(trial_lesson_id: str, lesson_id: str) -> GuidedAccess:
    if trial_lesson_id == lesson_id:
        return GuidedAccess(True, "trial_in_progress", trial_lesson_id)
    return GuidedAccess(False, "trial_used", trial_lesson_id)


async def get_access(user_id: str, lesson_id: str) -> GuidedAccess:
    """Read-only, for the app's lesson screen. Never claims the trial."""
    entitled = await _entitled(user_id)
    if entitled:
        return entitled
    try:
        row = await db.select_one(_TABLE, {"user_id": user_id})
    except Exception:
        return GuidedAccess(False, "unavailable")
    if not row:
        return GuidedAccess(True, "trial_available")
    return _trial_answer(str(row.get("lesson_id") or ""), lesson_id)


async def authorize(user_id: str, lesson_id: str) -> GuidedAccess:
    """At session mint: lets subscribers in, or claims (or resumes) a non-subscriber's trial."""
    entitled = await _entitled(user_id)
    if entitled:
        return entitled
    try:
        claimed = await db.rpc(_CLAIM_FN, {"p_user_id": user_id, "p_lesson_id": lesson_id})
    except Exception:
        return GuidedAccess(False, "unavailable")
    if not isinstance(claimed, str) or not claimed:
        return GuidedAccess(False, "unavailable")
    return _trial_answer(claimed, lesson_id)
