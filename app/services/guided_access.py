"""Who may start a guided voice lesson ("Aula com a Flua" in the app).

Subscribers and admins: always. A non-subscriber gets TRIAL_LIMIT trial lessons
per account (owner decision, 2026-11-04): each new lesson they start takes one,
they may resume any lesson already taken, and once the limit is reached any
other lesson is refused. The claim is atomic in SQL (claim_guided_lesson_trial_slot,
flueai/supabase/migrations/20261105_guided_lesson_trials_three.sql), so two
simultaneous starts can never pass the limit.

Failure policy:
- An unreadable subscription fails OPEN (treated as a subscriber), like
  lesson_timer and conversation_credits: an infra hiccup never locks a paying
  student out.
- An unreadable, unwritable or malformed trial answer fails CLOSED for a known
  non-subscriber: no free lesson on an error.
"""
from dataclasses import dataclass
from typing import Literal

from app.services import supabase_admin as db
from app.services.conversation_credits import is_admin
from app.services.user_data import get_subscription

Reason = Literal["subscriber", "trial_available", "trial_in_progress", "trial_used", "unavailable"]

TRIAL_LIMIT = 3

_TABLE = "guided_lesson_trials"
_CLAIM_FN = "claim_guided_lesson_trial_slot"


@dataclass(frozen=True)
class GuidedAccess:
    can_start: bool
    reason: Reason
    # This lesson when it is one of the trials, otherwise the latest trial taken.
    trial_lesson_id: str | None = None
    # The account's trial lessons, oldest first; None when they were not read (subscribers, errors).
    trial_lesson_ids: tuple[str, ...] | None = None
    is_admin: bool = False

    @property
    def trials_used(self) -> int | None:
        return None if self.trial_lesson_ids is None else len(self.trial_lesson_ids)


async def _is_subscriber(user_id: str) -> bool:
    try:
        return (await get_subscription(user_id)).isSubscribed
    except Exception:
        return True  # fail open, as the other budgets do


async def _entitled(user_id: str) -> GuidedAccess | None:
    """Admins and subscribers, who never touch the trials; None for everyone else."""
    if await is_admin(user_id):
        return GuidedAccess(True, "subscriber", is_admin=True)
    if await _is_subscriber(user_id):
        return GuidedAccess(True, "subscriber")
    return None


def _trial_answer(lesson_ids: tuple[str, ...], lesson_id: str) -> GuidedAccess:
    """What the trials already taken mean for lesson_id."""
    if lesson_id in lesson_ids:
        return GuidedAccess(True, "trial_in_progress", lesson_id, lesson_ids)
    latest = lesson_ids[-1] if lesson_ids else None
    if len(lesson_ids) < TRIAL_LIMIT:
        return GuidedAccess(True, "trial_available", latest, lesson_ids)
    return GuidedAccess(False, "trial_used", latest, lesson_ids)


async def get_access(user_id: str, lesson_id: str) -> GuidedAccess:
    """Read-only, for the app's lesson screen. Never claims a trial."""
    entitled = await _entitled(user_id)
    if entitled:
        return entitled
    try:
        rows = await db.select_many(
            _TABLE, {"user_id": user_id}, select="lesson_id", order="started_at.asc,lesson_id.asc",
        )
    except Exception:
        return GuidedAccess(False, "unavailable")
    return _trial_answer(tuple(str(row.get("lesson_id") or "") for row in rows), lesson_id)


async def authorize(user_id: str, lesson_id: str) -> GuidedAccess:
    """At session mint: lets subscribers in, or takes (or resumes) one of a non-subscriber's trials."""
    entitled = await _entitled(user_id)
    if entitled:
        return entitled
    try:
        claimed = await db.rpc(
            _CLAIM_FN, {"p_user_id": user_id, "p_lesson_id": lesson_id, "p_limit": TRIAL_LIMIT},
        )
    except Exception:
        return GuidedAccess(False, "unavailable")
    if not isinstance(claimed, dict):
        return GuidedAccess(False, "unavailable")
    granted, raw_ids = claimed.get("granted"), claimed.get("lessonIds")
    if not isinstance(granted, bool) or not isinstance(raw_ids, list):
        return GuidedAccess(False, "unavailable")
    lesson_ids = tuple(str(item) for item in raw_ids)
    answer = _trial_answer(lesson_ids, lesson_id)
    # The claim and the list must agree: a grant for a lesson not in the list, or a refusal while the
    # list has room or holds the lesson, is a malformed answer, and malformed fails closed.
    if granted and answer.reason == "trial_in_progress":
        return answer
    if not granted and answer.reason == "trial_used":
        return answer
    return GuidedAccess(False, "unavailable")
