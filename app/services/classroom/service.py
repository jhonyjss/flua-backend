from copy import deepcopy
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import get_settings
from app.schemas.classroom import Command, Start
from app.services import conversation_credits, guided_access
from app.services import supabase_admin as db
from app.services.classroom import content
from app.services.classroom import orchestrator as machine
from app.services.classroom import repository as repo
from app.services.user_data import get_subscription


def enabled(user):
    cfg = get_settings()
    if not cfg.classroom_v2_enabled or (
        cfg.classroom_v2_users and user not in cfg.classroom_v2_users.split(",")
    ):
        raise HTTPException(404, {"code": "classroom_disabled"})


async def budget(user):
    # Unlike the legacy flow, a subscription lookup error must not grant access.
    if await conversation_credits.is_admin(user):
        return 3600
    sub = await get_subscription(user)
    return 900 if sub.isSubscribed else 600


async def authorize(user, lesson, claim=False):
    await budget(user)  # fail before guided_access's legacy fail-open policy
    access = await (
        guided_access.authorize(user, lesson)
        if claim
        else guided_access.get_access(user, lesson)
    )
    if not access.can_start:
        raise HTTPException(403, {"code": "guided_lesson_unavailable"})


async def start(user, body: Start):
    enabled(user)
    plan = content.lesson(body.lessonId, body.contentVersion)
    existing = await db.select_one(
        "classroom_sessions", {"id": str(body.sessionId), "user_id": user}
    )
    if existing:
        if (
            existing["lesson_id"] != body.lessonId
            or existing["content_version"] != body.contentVersion
        ):
            raise HTTPException(409, {"code": "session_conflict"})
        return existing
    await authorize(user, body.lessonId, claim=True)
    row = await db.insert(
        "classroom_sessions",
        {
            "id": str(body.sessionId),
            "user_id": user,
            "lesson_id": body.lessonId,
            "content_version": body.contentVersion,
            "state": machine.initial(plan),
        },
    )
    if not row:
        raise HTTPException(503, {"code": "classroom_storage_unavailable"})
    return row


async def command(user, session, body: Command):
    row = await repo.get(user, session)
    # Resolve idempotent replay before applying lifecycle/version checks.
    old = await db.select_one(
        "classroom_events", {"session_id": session, "event_id": str(body.commandId)}
    )
    if old:
        return await repo.save(
            user,
            row,
            str(body.commandId),
            "command." + body.type,
            old["state"],
            body.model_dump(mode="json"),
        )
    if row["version"] != body.expectedVersion:
        raise HTTPException(409, {"code": "state_version", "version": row["version"]})
    s = deepcopy(row["state"])
    if s["status"] in ("completed", "expired", "ended"):
        raise HTTPException(410, {"code": "session_closed"})
    plan = content.lesson(row["lesson_id"], row["content_version"])
    if body.type in ("resume", "ready"):
        await authorize(user, row["lesson_id"])
        s["status"] = "active"
        s["pendingInstruction"] = s["pendingInstruction"] or (
            machine.teach(plan, s)
            if not s["lastDelivered"]
            else machine.pending(plan, s)
        )
    elif body.type in ("pause", "stop", "disconnect"):
        s["status"] = "ended" if body.type == "stop" else "paused"
        if body.type == "disconnect":
            s["disconnectRequested"] = True
    elif body.type == "set_language":
        if body.scope == "session":
            s["language"] = body.language
        s["replyLanguage"] = body.language
        s["pendingInstruction"] = "Confirme o idioma e retome. " + machine.pending(
            plan, s
        )
    elif body.type == "text_turn":
        s["pendingText"] = body.text
    elif body.type == "interrupt":
        s["pendingInstruction"] = ""
    s["generation"] += 1
    return await repo.save(
        user,
        row,
        str(body.commandId),
        "command." + body.type,
        s,
        body.model_dump(mode="json"),
    )


async def provider_event(user, session, owner, event_type, update):
    for _ in range(3):
        row = await repo.get(user, session)
        state = update(deepcopy(row["state"]))
        if state is None:
            return row
        try:
            result = await repo.save(
                user, row, str(uuid4()), event_type, state, owner=owner
            )
            return {**row, **result}
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
    raise HTTPException(409, {"code": "state_version"})


async def finish_if_completed(user, session, owner=None):
    from datetime import UTC, datetime

    from app.schemas.app_progress import SessionResultRequest
    from app.services import app_progress

    row = await repo.get(user, session)
    s = row["state"]
    if s["status"] != "completed" or s["pendingInstruction"] or s.get("outcome"):
        return row
    plan = content.lesson(row["lesson_id"], row["content_version"])
    if row["content_version"].startswith("web-"):
        from app.services import learning

        for n, item in enumerate(plan["items"]):
            if s["statuses"][n] in ("reached", "practised"):
                await learning.save_topic_completion(user, row["lesson_id"], item["id"])
        await learning.complete_lesson(
            user,
            row["lesson_id"],
            {
                "topicsCompleted": len(plan["items"]),
                "timeSpentSeconds": 0,
                "rating": 5
                * sum(status == "reached" for status in s["statuses"])
                / len(plan["items"]),
                "sessionId": session,
            },
        )
        return await provider_event(
            user,
            session,
            owner,
            "lesson.completed",
            lambda state: {**state, "outcome": {"completed": True}},
        )
    request = SessionResultRequest(
        contentVersion=row["content_version"],
        activityId=row["lesson_id"],
        kind="voice_lesson",
        completedAt=datetime.now(UTC),
        attempts=[
            {
                "exerciseId": "voice:" + item["id"],
                "conceptId": item["id"],
                "correct": s["statuses"][n] == "reached",
            }
            for n, item in enumerate(plan["items"])
        ],
    )
    # Existing finish_app_session RPC is idempotent by user+session. Retry after a crash is safe.
    result = await app_progress.finish_session(user, session, request)
    return await provider_event(
        user,
        session,
        owner,
        "lesson.completed",
        lambda state: {**state, "outcome": result.model_dump(mode="json")},
    )
