"""The app's progress routes (flueai-app docs/backend-contract.md, 3.1, 3.3, 3.4)."""
from fastapi import APIRouter, Depends, Path, Query

from app.core.auth import AuthUser, get_current_user
from app.core.rate_limit import rate_limited
from app.schemas.app_progress import (
    DueConcept,
    SessionResult,
    SessionResultRequest,
    Summary,
)
from app.services import app_progress

router = APIRouter(prefix="/api/users/me", tags=["app-progress"])


@router.get("/summary", response_model=Summary)
async def get_summary(user: AuthUser = Depends(get_current_user)) -> Summary:
    return await app_progress.summary(user.id)


@router.put("/sessions/{session_id}/result", response_model=SessionResult)
async def finish_session(
    body: SessionResultRequest,
    session_id: str = Path(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$"),
    user: AuthUser = Depends(rate_limited("session_result", max_requests=60, window_seconds=60)),
) -> SessionResult:
    """Idempotent per (user, sessionId): a resend returns the stored result with replayed=true."""
    return await app_progress.finish_session(user.id, session_id, body)


@router.get("/concepts/due", response_model=list[DueConcept])
async def concepts_due(
    limit: int = Query(10, ge=1, le=50), user: AuthUser = Depends(get_current_user),
) -> list[DueConcept]:
    return await app_progress.due_concepts(user.id, limit)
