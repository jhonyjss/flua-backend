"""Results of "Rotas com a Flua" events on the account (flueai-app docs/rotas/02-progresso-e-fala-no-backend.md).

Same route and idempotency as the lessons (PUT /api/users/me/sessions/{id}/result, kind "route_event").
This module validates the attempts against the route manifest (app/data/route_manifest.json), computes
the first-time XP and the stamp, and calls finish_route_event
(flueai/supabase/migrations/20261117_route_progress.sql), which decides first time vs repeat, the order,
the ledger, the streak and the review.

The manifest mirrors the app's src/content/routes/travel.ts; change both, and contentVersion, together.
"""
import json
from functools import cache
from pathlib import Path

from fastapi import HTTPException

from app.schemas.app_progress import RouteTrackState, SessionOutcome, SessionResultRequest
from app.services import supabase_admin as db

ROUTE = "travel"
_MANIFEST = Path(__file__).resolve().parent.parent / "data" / "route_manifest.json"

# rotas-com-a-flua.md §5: item right 2, sentence said right 1, "Sua vez" 3, event 5, gold 3.
XP_ITEM = 2
XP_SPEECH = 1
XP_YOUR_TURN = 3
XP_EVENT = 5
XP_GOLD = 3

SPEAK_MODES = ("nice", "after_miss", "again")


@cache
def manifest() -> dict:
    return json.loads(_MANIFEST.read_text())


def _route() -> dict:
    return manifest()["routes"][ROUTE]


def _refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def concepts_of(event_id: str) -> list[str]:
    """The event's key sentences in the spaced review: one concept per "Sua vez" turn."""
    turns = _route()["events"][event_id]["turns"]
    return [f"route:{event_id}:t{n}" for n in range(1, len(turns) + 1)]


def score(request: SessionResultRequest) -> dict:
    """The first-time XP and the stamp; refuses what can't be recorded (409 or 422, never retried)."""
    if request.contentVersion != manifest()["contentVersion"]:
        raise _refuse(409, "content_version", "Atualize o app para continuar.")
    event = _route()["events"].get(request.activityId)
    if not event:
        raise _refuse(422, "invalid_activity", f"Event {request.activityId} cannot be recorded.")

    items = {item["id"]: item for item in event["items"]}
    turns = set(event["turns"])
    speak_ids = {f"speak:{turn}" for turn in turns}
    for item in event["items"]:
        speak_ids.update(f"speak:{item['id']}:{mode}" for mode in SPEAK_MODES if mode != "again" or item["write"])

    answered: dict[str, bool] = {}
    first_try: dict[str, bool] = {}
    spoken: list[tuple[str, bool, bool]] = []
    for attempt in request.attempts:
        if attempt.exerciseId in items:
            answered[attempt.exerciseId] = answered.get(attempt.exerciseId, False) or attempt.correct
            first_try.setdefault(attempt.exerciseId, attempt.correct)
        elif attempt.exerciseId in speak_ids:
            spoken.append((attempt.exerciseId, attempt.correct, attempt.usedHint))
        else:
            raise _refuse(422, "invalid_attempts", f"Unknown attempt {attempt.exerciseId}.")
    said = {exercise for exercise, _, _ in spoken}
    if set(answered) != set(items) or not all(f"speak:{turn}" in said for turn in turns):
        raise _refuse(422, "invalid_attempts", "Attempts do not cover every item and every turn.")

    # Gold: every sentence asked came out right (skipped or failed twice is a miss).
    gold = all(correct for _, correct, _ in spoken)
    # A sentence pays once, and not after "Ver a frase".
    paid = {exercise for exercise, correct, hint in spoken if correct and not hint}
    xp = (
        sum(1 for right in answered.values() if right) * XP_ITEM
        + len(paid) * XP_SPEECH
        + XP_YOUR_TURN
        + XP_EVENT
        + (XP_GOLD if gold else 0)
    )
    return {
        "xp": xp,
        "stamp": "gold" if gold else "silver",
        "items_correct": sum(1 for right in first_try.values() if right),
        "items_total": len(items),
    }


async def finish(user_id: str, session_id: str, request: SessionResultRequest) -> tuple[bool, SessionOutcome]:
    scored = score(request)
    try:
        applied = await db.rpc("finish_route_event", {
            "p_user_id": user_id,
            "p_session_id": session_id,
            "p_client": request.client,
            "p_route": ROUTE,
            "p_event_id": request.activityId,
            "p_completed_at": request.completedAt.isoformat(),
            "p_origin": request.origin,
            "p_attempts": [attempt.model_dump() for attempt in request.attempts],
            "p_items_correct": scored["items_correct"],
            "p_items_total": scored["items_total"],
            "p_first_xp": scored["xp"],
            "p_stamp": scored["stamp"],
            "p_order": _route()["order"],
            "p_concepts": concepts_of(request.activityId),
        })
    except HTTPException as err:
        if "activity_locked" in str(err.detail):
            raise _refuse(409, "activity_locked", f"Event {request.activityId} is locked.") from err
        raise
    if not isinstance(applied, dict) or "result" not in applied:
        raise HTTPException(502, "Unexpected answer from finish_route_event")
    return bool(applied.get("replayed")), SessionOutcome(**applied["result"])


async def track(user_id: str) -> RouteTrackState:
    rows = await db.select_many("route_stamps", {"user_id": user_id, "route": ROUTE}, select="event_id,stamp")
    stamps = {row["event_id"]: row["stamp"] for row in rows}
    order = _route()["order"]
    return RouteTrackState(
        completedActivityIds=[event for event in order if event in stamps],
        currentActivityId=next((event for event in order if event not in stamps), None),
        stamps=stamps,
    )
