"""Versioned, authenticated server-owned classroom endpoints."""

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.core.auth import AuthUser
from app.core.rate_limit import rate_limited
from app.schemas.classroom import Command, Connection, Start
from app.services.classroom import realtime_connection, service
from app.services.classroom import repository as repo

router = APIRouter(prefix="/api/classroom", tags=["classroom"])
user_dep = Depends(rate_limited("classroom", max_requests=120, window_seconds=60))


def public(row):
    return {
        "sessionId": row["id"],
        "lessonId": row["lesson_id"],
        "contentVersion": row["content_version"],
        "version": row["version"],
        "state": row["state"],
        "orchestrationVersion": 2,
    }


@router.post("/sessions", status_code=201)
async def start(body: Start, user: AuthUser = user_dep):
    return public(await service.start(user.id, body))


@router.get("/sessions/{session_id}")
async def get(session_id: UUID, user: AuthUser = user_dep):
    return public(await service.finish_if_completed(user.id, str(session_id)))


@router.post("/sessions/{session_id}/connection", status_code=201)
async def connect(session_id: UUID, body: Connection, user: AuthUser = user_dep):
    return await realtime_connection.connect(user.id, str(session_id), body)


@router.post("/sessions/{session_id}/commands", status_code=202)
async def command(session_id: UUID, body: Command, user: AuthUser = user_dep):
    return await service.command(user.id, str(session_id), body)


@router.get("/sessions/{session_id}/events")
async def events(
    session_id: UUID,
    request: Request,
    after: int = Query(0, ge=0),
    user: AuthUser = user_dep,
):
    session = str(session_id)
    await repo.get(user.id, session)

    async def stream():
        cursor = after
        # Bounded connection lifetime forces authentication to be rechecked.
        for _ in range(120):
            if await request.is_disconnected():
                break
            rows = await repo.events(user.id, session, cursor)
            for row in rows:
                cursor = row["sequence"]
                data = {
                    "eventId": row["event_id"],
                    "sequence": cursor,
                    "sessionId": session,
                    "stateVersion": cursor,
                    "type": row["type"],
                    "data": row["state"],
                }
                yield f"id: {cursor}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            if not rows:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
