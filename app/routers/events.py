"""POST /api/events — product events from the app, in batches."""
from fastapi import APIRouter, Depends

from app.core.auth import AuthUser
from app.core.rate_limit import rate_limited
from app.schemas.events import AppEventsRequest
from app.schemas.learning import OkResponse
from app.services import app_events

router = APIRouter(prefix="/api", tags=["events"])


@router.post("/events", response_model=OkResponse, status_code=201)
async def save_events(
    body: AppEventsRequest,
    # The app batches (up to 50 events, every 30 s or when it goes to the background): a few
    # requests a minute is normal use, not a loop.
    user: AuthUser = Depends(rate_limited("app_events", max_requests=30, window_seconds=60)),
) -> OkResponse:
    await app_events.save(user.id, body)
    return OkResponse()
