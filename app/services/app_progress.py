"""Progress of the app's "Fundamentos" trail on the account (flueai-app docs/backend-contract.md).

The server decides: XP, streak, unlocking, achievements and the review schedule are applied by
the Postgres function finish_app_session (flueai/supabase/migrations/20261015_app_progress.sql)
in one transaction, idempotent per (user, session). This module validates the payload against
the content manifest, computes precision and builds the summary.

The manifest (app/data/fundamentals_manifest.json) is generated from the app's content; regenerate
it whenever the app's CONTENT_VERSION changes, before that app version ships.
"""
import json
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.schemas.app_progress import (
    AchievementOwned,
    AppProfile,
    DueConcept,
    SessionOutcome,
    SessionResult,
    SessionResultRequest,
    StreakState,
    Summary,
    Tracks,
    TrackState,
    XpTotals,
)
from app.services import supabase_admin as db

TRACK = "fundamentals"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
_MANIFEST = Path(__file__).resolve().parent.parent / "data" / "fundamentals_manifest.json"


@cache
def manifest() -> dict:
    data = json.loads(_MANIFEST.read_text())
    data["byId"] = {activity["id"]: activity for activity in data["activities"]}
    return data


def sao_paulo_day(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(SAO_PAULO).date()


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def main_ids(request: SessionResultRequest) -> list[str]:
    """The ids that count for precision; refuses what can't be recorded (409 or 422, never retried)."""
    m = manifest()
    if request.contentVersion != m["contentVersion"]:
        raise _refuse(409, "content_version", "Atualize o app para continuar.")
    if request.kind in ("review", "practice"):
        if not request.attempts:
            raise _refuse(422, "invalid_attempts", "A review needs attempts.")
        return list(dict.fromkeys(attempt.exerciseId for attempt in request.attempts))
    activity = m["byId"].get(request.activityId)
    expected_kind = "lesson" if request.kind == "voice_lesson" else request.kind
    if not activity or activity["kind"] != expected_kind:
        raise _refuse(422, "invalid_activity", f"Activity {request.activityId} cannot be recorded.")
    answered = {attempt.exerciseId for attempt in request.attempts}
    if request.kind == "voice_lesson":
        # One attempt per concept, `correct` when the learner said it alone.
        ids = [f"voice:{concept}" for concept in activity["concepts"]]
    else:
        ids = list(activity["mainExerciseIds"])
    if not all(exercise in answered for exercise in ids):
        raise _refuse(422, "invalid_attempts", "Attempts do not cover every main exercise.")
    return ids


def first_try_correct(request: SessionResultRequest, ids: list[str]) -> int:
    first: dict[str, bool] = {}
    for attempt in request.attempts:
        first.setdefault(attempt.exerciseId, attempt.correct)
    return sum(1 for exercise in ids if first.get(exercise))


async def finish_session(user_id: str, session_id: str, request: SessionResultRequest) -> SessionResult:
    ids = main_ids(request)
    m = manifest()
    activity = m["byId"].get(request.activityId)
    try:
        applied = await db.rpc("finish_app_session", {
            "p_user_id": user_id,
            "p_session_id": session_id,
            "p_client": request.client,
            "p_track": TRACK,
            "p_activity_id": request.activityId,
            "p_kind": request.kind,
            "p_completed_at": request.completedAt.isoformat(),
            "p_origin": request.origin,
            "p_attempts": [attempt.model_dump() for attempt in request.attempts],
            "p_first_try_correct": first_try_correct(request, ids),
            "p_main_total": len(ids),
            "p_order": [a["id"] for a in m["activities"]],
            "p_kinds": [a["kind"] for a in m["activities"]],
            "p_concepts": activity["concepts"] if activity else [],
        })
    except HTTPException as err:
        if "activity_locked" in str(err.detail):
            raise _refuse(409, "activity_locked", f"Activity {request.activityId} is locked.") from err
        raise
    if not isinstance(applied, dict) or "result" not in applied:
        raise HTTPException(502, "Unexpected answer from finish_app_session")
    return SessionResult(
        replayed=bool(applied.get("replayed")),
        result=SessionOutcome(**applied["result"]),
        summary=await summary(user_id),
    )


def _shown_streak(row: dict | None, today: date) -> StreakState:
    """A streak alive today or yesterday counts; after a missed day it shows 0 until the next practice."""
    if not row:
        return StreakState(current=0, longest=0, lastPracticeDay=None)
    last = row.get("last_practice_date")
    alive = last in (today.isoformat(), (today - timedelta(days=1)).isoformat())
    return StreakState(
        current=int(row.get("current_streak") or 0) if alive else 0,
        longest=int(row.get("longest_streak") or 0),
        lastPracticeDay=last,
    )


async def summary(user_id: str) -> Summary:
    today = sao_paulo_day()
    profile = await db.select_one("profiles", {"id": user_id})
    if not profile:
        raise HTTPException(404, "Perfil não encontrado")
    ledger_today = await db.select_many("xp_ledger", {"user_id": user_id, "local_day": today.isoformat()}, select="amount")
    streak = await db.select_one("user_streaks", {"user_id": user_id})
    achievements = await db.select_many(
        "user_achievements", {"user_id": user_id}, select="achievement_id,unlocked_at", order="unlocked_at.asc",
    )
    due = await db.select_many(
        "concept_reviews", {"user_id": user_id}, select="concept_id", op_filters={"due_day": f"lte.{today.isoformat()}"},
    )
    done = await db.select_many(
        "track_completions", {"user_id": user_id, "track": TRACK}, select="activity_id", order="completed_at.asc",
    )
    completed = [row["activity_id"] for row in done]
    current = next((a["id"] for a in manifest()["activities"] if a["id"] not in completed), None)
    return Summary(
        profile=AppProfile(
            fullName=profile.get("full_name"),
            dailyGoalXp=profile.get("daily_goal_xp") or 20,
            motivation=profile.get("motivation") or "daily",
        ),
        xp=XpTotals(total=int(profile.get("xp") or 0), today=sum(int(row.get("amount") or 0) for row in ledger_today)),
        streak=_shown_streak(streak, today),
        achievements=[AchievementOwned(id=row["achievement_id"], unlockedAt=row.get("unlocked_at")) for row in achievements],
        reviewsDue=len(due),
        tracks=Tracks(fundamentals=TrackState(completedActivityIds=completed, currentActivityId=current)),
        serverDay=today.isoformat(),
    )


async def due_concepts(user_id: str, limit: int) -> list[DueConcept]:
    """Concepts due today or earlier, the most overdue first."""
    rows = await db.select_many(
        "concept_reviews",
        {"user_id": user_id},
        select="concept_id,due_day,stage",
        order="due_day.asc",
        limit=limit,
        op_filters={"due_day": f"lte.{sao_paulo_day().isoformat()}"},
    )
    return [DueConcept(conceptId=r["concept_id"], dueDay=r["due_day"], stage=int(r.get("stage") or 0)) for r in rows]
