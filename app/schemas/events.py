"""POST /api/events — product events from the app (owner decision 2026-11-05: first-party, no
third-party analytics SDK). What the learner did, never what they said or typed. The app's side of
the contract is flueai-app src/services/analytics/events.ts; the table is flueai
supabase/migrations/20261105_app_events.sql."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

# The events the app sends today (flueai-app src/services/analytics/events.ts). Documentation only:
# any name in the table's format is accepted, so an app release that adds an event before this list
# does not lose the rest of its batch.
KNOWN_EVENTS = (
    "screen_view",
    "paywall_view",
    "subscribe_click",
    "purchase_result",
    "restore_click",
    "guided_lesson_start",
    "guided_lesson_complete",
    "lesson_complete",
    "trial_exhausted",
    "sign_up",
    "login",
)
EventName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,39}$")]

ParamKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,31}$")]
# Flat values only: ids, plan names, counts, flags. Long text has no place in an event.
ParamValue = Annotated[str, StringConstraints(max_length=120)] | int | float | bool | None


class AppEvent(BaseModel):
    # Made by the app when the event happens: a batch sent twice keeps the first row.
    eventId: UUID
    name: EventName
    occurredAt: datetime
    params: dict[ParamKey, ParamValue] = Field(default_factory=dict, max_length=12)


class AppEventsRequest(BaseModel):
    client: Literal["ios", "android", "web"]
    appVersion: str = Field("", max_length=32)
    events: list[AppEvent] = Field(min_length=1, max_length=50)
