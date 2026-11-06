"""POST /api/events — product events from the app, one row each in app_events."""
import json
from datetime import datetime, timedelta, timezone

import httpx

USER_ID = "00000000-0000-0000-0000-000000000001"  # make_token's default subject
EVENT_A = "5b1f0d2e-1c3a-4d5e-8f60-718293a4b5c6"
EVENT_B = "6c2e1f3a-2d4b-4e6f-9a71-8293a4b5c6d7"


def _now_iso(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def _body(*events, client="android"):
    return {"client": client, "appVersion": "1.0.1 (7)", "events": list(events)}


def _event(event_id=EVENT_A, name="subscribe_click", params=None, occurred_at=None):
    return {
        "eventId": event_id,
        "name": name,
        "occurredAt": occurred_at or _now_iso(),
        "params": {"plan": "pro", "period": "monthly", "signed_in": True} if params is None else params,
    }


def recording_supabase(captured: list, *, status: int = 201):
    """PostgREST stand-in: records each write and answers like an insert (or fails with `status`)."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured.append({
                "path": request.url.path,
                "on_conflict": request.url.params.get("on_conflict"),
                "prefer": request.headers.get("prefer"),
                "rows": json.loads(request.content),
            })
            return httpx.Response(status, json=[] if status < 300 else {"message": "db down"})
        return httpx.Response(200, json=[])

    return handler


def test_a_batch_becomes_one_row_per_event_for_the_user(client, auth_headers, mock_transport):
    captured: list = []
    mock_transport(recording_supabase(captured))
    sent_at = _now_iso(minutes=-5)

    res = client.post(
        "/api/events",
        json=_body(
            _event(occurred_at=sent_at),
            _event(EVENT_B, "lesson_complete", {"lesson_id": "fund-u1-l2", "kind": "lesson"}, sent_at),
        ),
        headers=auth_headers,
    )

    assert res.status_code == 201
    assert len(captured) == 1
    write = captured[0]
    assert write["path"] == "/rest/v1/app_events"
    assert write["on_conflict"] == "event_id"
    assert "resolution=ignore-duplicates" in write["prefer"]  # a resent batch keeps the first rows
    assert write["rows"] == [
        {
            "event_id": EVENT_A,
            "user_id": USER_ID,
            "name": "subscribe_click",
            "occurred_at": datetime.fromisoformat(sent_at).isoformat(),
            "client": "android",
            "app_version": "1.0.1 (7)",
            "params": {"plan": "pro", "period": "monthly", "signed_in": True},
        },
        {
            "event_id": EVENT_B,
            "user_id": USER_ID,
            "name": "lesson_complete",
            "occurred_at": datetime.fromisoformat(sent_at).isoformat(),
            "client": "android",
            "app_version": "1.0.1 (7)",
            "params": {"lesson_id": "fund-u1-l2", "kind": "lesson"},
        },
    ]


def test_a_device_clock_far_off_is_replaced_by_the_server_time(client, auth_headers, mock_transport):
    captured: list = []
    mock_transport(recording_supabase(captured))
    before = datetime.now(timezone.utc)

    res = client.post(
        "/api/events",
        json=_body(_event(occurred_at=_now_iso(days=-90)), _event(EVENT_B, occurred_at=_now_iso(days=2))),
        headers=auth_headers,
    )

    assert res.status_code == 201
    after = datetime.now(timezone.utc)
    for row in captured[0]["rows"]:
        assert before <= datetime.fromisoformat(row["occurred_at"]) <= after


def test_an_event_weeks_old_from_the_offline_queue_keeps_its_time(client, auth_headers, mock_transport):
    captured: list = []
    mock_transport(recording_supabase(captured))
    sent_at = _now_iso(days=-20)

    client.post("/api/events", json=_body(_event(occurred_at=sent_at)), headers=auth_headers)

    assert captured[0]["rows"][0]["occurred_at"] == datetime.fromisoformat(sent_at).isoformat()


def test_unknown_or_oversized_events_are_refused_before_any_write(client, auth_headers, mock_transport):
    captured: list = []
    mock_transport(recording_supabase(captured))
    refused = [
        _body(_event(name="Credit-Card")),                                         # name outside the table's format
        _body(_event(params={"Plan": "pro"})),                                     # key outside [a-z_]
        _body(_event(params={"note": "x" * 121})),                                 # long text
        _body(_event(params={"items": ["a", "b"]})),                               # nested value
        _body(_event(params={f"k{chr(97 + i)}": i for i in range(13)})),           # 13 params
        _body(*[_event(f"00000000-0000-4000-8000-{i:012d}") for i in range(51)]),  # 51 events
        {"client": "android", "events": []},                                       # empty batch
        _body(_event(), client="desktop"),                                         # unknown client
    ]
    for body in refused:
        res = client.post("/api/events", json=body, headers=auth_headers)
        assert res.status_code == 422, body
    assert captured == []


def test_events_need_a_session(client):
    assert client.post("/api/events", json=_body(_event())).status_code == 401


def test_a_failed_write_answers_502_without_the_database_text(client, auth_headers, mock_transport):
    captured: list = []
    mock_transport(recording_supabase(captured, status=500))

    res = client.post("/api/events", json=_body(_event()), headers=auth_headers)

    assert res.status_code == 502
    assert "db down" not in res.text


def test_an_event_newer_than_this_backend_is_stored_with_the_rest_of_its_batch(client, auth_headers, mock_transport):
    # An app release can add an event before this list knows it: the batch must not be lost for it.
    captured: list = []
    mock_transport(recording_supabase(captured))

    res = client.post(
        "/api/events",
        json=_body(_event(), _event(EVENT_B, "streak_shared", {"days": 7})),
        headers=auth_headers,
    )

    assert res.status_code == 201
    assert [row["name"] for row in captured[0]["rows"]] == ["subscribe_click", "streak_shared"]
