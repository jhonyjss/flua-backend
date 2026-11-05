"""Product events from the app (app_events). The table lives in the flueai repo's migrations: RLS on
and no policy, so only this service-role client reads and writes it. Rows cascade from profiles on
account deletion."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.schemas.events import AppEventsRequest
from app.services import supabase_admin as db

logger = logging.getLogger(__name__)

TABLE = "app_events"

# The device clock decides occurred_at, within reason: an offline queue can hold events for weeks,
# a wrong clock can say anything. Outside this window the server's time is used instead.
_OLDEST = timedelta(days=60)
_NEWEST = timedelta(hours=1)


def _occurred_at(sent: datetime, now: datetime) -> datetime:
    when = sent if sent.tzinfo else sent.replace(tzinfo=timezone.utc)
    return when if now - _OLDEST <= when <= now + _NEWEST else now


def event_rows(user_id: str, body: AppEventsRequest, now: datetime) -> list[dict]:
    """The batch as table rows: snake_case columns, one row per event."""
    return [
        {
            "event_id": str(event.eventId),
            "user_id": user_id,
            "name": event.name,
            "occurred_at": _occurred_at(event.occurredAt, now).isoformat(),
            "client": body.client,
            "app_version": body.appVersion,
            "params": event.params,
        }
        for event in body.events
    ]


async def save(user_id: str, body: AppEventsRequest, now: datetime | None = None) -> None:
    """An event sent twice keeps its first row. A failed write is logged here (the app drops the
    answer, so this is the only trace of lost events) and answered without the database's text."""
    rows = event_rows(user_id, body, now or datetime.now(timezone.utc))
    try:
        await db.upsert(TABLE, rows, on_conflict="event_id", ignore_duplicates=True)
    except HTTPException as err:
        logger.warning("app events not saved (user %s, %d events): %s", user_id, len(rows), err.detail)
        raise HTTPException(502, "Não foi possível gravar os eventos.") from err
