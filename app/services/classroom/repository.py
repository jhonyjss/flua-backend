import hashlib
import json

from fastapi import HTTPException

from app.services import supabase_admin as db


def check(result):
    if not isinstance(result, dict):
        raise HTTPException(503, {"code": "classroom_storage_unavailable"})
    if result.get("error"):
        raise HTTPException(
            result["error"],
            {
                "code": "classroom_conflict"
                if result["error"] == 409
                else "session_not_found"
            },
        )
    return result


async def get(user: str, session: str):
    row = await db.select_one("classroom_sessions", {"id": session, "user_id": user})
    if not row:
        raise HTTPException(404, {"code": "session_not_found"})
    return row


async def save(user, row, event_id, event_type, state, payload=None, owner=None):
    fingerprint = hashlib.sha256(
        json.dumps(payload if payload is not None else state, sort_keys=True).encode()
    ).hexdigest()
    return check(
        await db.rpc(
            "classroom_transition",
            {
                "p_user_id": user,
                "p_session_id": row["id"],
                "p_version": row["version"],
                "p_event_id": event_id,
                "p_fingerprint": fingerprint,
                "p_type": event_type,
                "p_state": state,
                "p_lease_owner": owner,
            },
        )
    )


async def lease(user, session, owner, action, limit):
    return check(
        await db.rpc(
            "classroom_lease",
            {
                "p_user_id": user,
                "p_session_id": session,
                "p_owner": owner,
                "p_action": action,
                "p_limit": limit,
            },
        )
    )


async def events(user, session, after):
    await get(user, session)
    return await db.select_many(
        "classroom_events",
        {"session_id": session},
        order="sequence.asc",
        limit=100,
        op_filters={"sequence": f"gt.{after}"},
    )
