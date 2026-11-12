"""The month's pool of Flua voice minutes (owner decision 2026-11-12): 60 min Starter, 120 min Pro,
spent by lessons with Flua; free trial lessons and admins never touch it."""
import datetime as dt
import json
import re

import httpx

from app.services import voice_minutes

USER_ID = "00000000-0000-0000-0000-000000000001"  # conftest.make_token's default subject
OTHER_USER = "00000000-0000-0000-0000-0000000000ff"


def _backend(*, plan_level=None, role="student", lesson_consumed=0, month_consumed=0, other_rows=(),
             month_fails=False, rpc_fails=False, stripe_fails=False, lesson_write_fails=False):
    """Supabase as seen from the backend, with the two usage tables kept in memory.

    conversation_credits answers like PostgREST: a read returns only the row its user_id and
    period_key filters select, and add_voice_seconds upserts one (user, month) row. `other_rows`
    adds (user_id, period_key, seconds) rows that a correct query must never pick up.
    Returns (handler, state): state["month"] is this account's seconds this month and
    state["month_writes"] every add_voice_seconds body."""
    month = voice_minutes.period_key()
    rows = {(USER_ID, month): month_consumed} if month_consumed else {}
    rows.update({(user, key): seconds for user, key, seconds in other_rows})
    state = {"lesson": lesson_consumed, "month_writes": [], "rows": rows}

    def mine() -> int:
        return state["rows"].get((USER_ID, month), 0)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "stripe_subscriptions" in path:
            if stripe_fails:
                return httpx.Response(500, json={"message": "down"})
            found = [] if plan_level is None else [{"status": "active", "plan_level": plan_level}]
            return httpx.Response(200, json=found)
        if "profiles" in path:
            return httpx.Response(200, json=[{"id": "u", "role": role}])
        if path.endswith("/rpc/add_voice_seconds"):
            if month_fails or rpc_fails:
                return httpx.Response(500, json={"message": "down"})
            body = json.loads(request.content)
            state["month_writes"].append(body)
            key = (body["p_user_id"], body["p_period_key"])
            state["rows"][key] = state["rows"].get(key, 0) + body["p_delta"]
            return httpx.Response(200, json=state["rows"][key])
        if "conversation_credits" in path:
            if month_fails or request.method != "GET":
                return httpx.Response(500, json={"message": "unexpected"})
            user = request.url.params.get("user_id", "").removeprefix("eq.")
            key = request.url.params.get("period_key", "").removeprefix("eq.")
            seconds = state["rows"].get((user, key))
            return httpx.Response(200, json=[] if seconds is None else [{"id": "m1", "consumed_seconds": seconds}])
        if "lesson_time_usage" in path:
            if request.method == "GET":
                found = [{"id": "l1", "consumed_seconds": state["lesson"], "active_seconds": 0}] if state["lesson"] else []
                return httpx.Response(200, json=found)
            if lesson_write_fails:
                return httpx.Response(400, json={"message": "boom"})
            body = json.loads(request.content or b"{}")
            state["lesson"] = body.get("consumed_seconds", state["lesson"])
            return httpx.Response(201 if request.method == "POST" else 200, json=[{"id": "l1"}])
        return httpx.Response(200, json=[])

    state["mine"] = mine
    return handler, state


def _minutes(client, auth_headers):
    res = client.get("/api/users/me/voice/minutes", headers=auth_headers)
    assert res.status_code == 200
    return res.json()


def test_starter_month_is_sixty_minutes(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="starter_monthly", month_consumed=600)
    mock_transport(handler)
    data = _minutes(client, auth_headers)
    assert data["planLevel"] == "starter"
    assert data["limitSeconds"] == 3600
    assert data["consumedSeconds"] == 600
    assert data["remainingSeconds"] == 3000
    assert data["expired"] is False
    assert re.fullmatch(r"\d{4}-\d{2}", data["periodKey"])
    assert "applies" not in data


def test_pro_month_is_one_hundred_twenty_minutes(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="pro_yearly", month_consumed=7200)
    mock_transport(handler)
    data = _minutes(client, auth_headers)
    assert (data["limitSeconds"], data["remainingSeconds"], data["expired"]) == (7200, 0, True)


def test_free_account_has_no_pool_and_is_never_expired(client, auth_headers, mock_transport):
    handler, _ = _backend(month_consumed=999)
    mock_transport(handler)
    data = _minutes(client, auth_headers)
    assert (data["planLevel"], data["limitSeconds"], data["expired"]) == ("free", 0, False)


def test_admin_is_unlimited(client, auth_headers, mock_transport):
    handler, _ = _backend(role="admin")
    mock_transport(handler)
    data = _minutes(client, auth_headers)
    assert data["isUnlimited"] is True
    assert data["expired"] is False


def test_the_month_is_the_calendar_month_in_sao_paulo():
    # 01:00 UTC on Dec 1st is still Nov 30th, 22:00, in Brazil.
    assert voice_minutes.period_key(dt.datetime(2026, 12, 1, 1, 0, tzinfo=dt.UTC)) == "2026-11"
    assert voice_minutes.period_key(dt.datetime(2026, 12, 1, 3, 0, tzinfo=dt.UTC)) == "2026-12"


def test_lesson_heartbeat_spends_the_lesson_and_the_month(client, auth_headers, mock_transport):
    handler, state = _backend(plan_level="starter_monthly", month_consumed=3100)
    mock_transport(handler)
    res = client.post("/api/users/me/lessons/L1/time/heartbeat", json={"deltaSeconds": 200}, headers=auth_headers)
    data = res.json()
    # The forged 200 s beat is clamped to 90 in both budgets.
    assert state["lesson"] == 90
    assert state["mine"]() == 3190
    assert state["month_writes"] == [
        {"p_user_id": USER_ID, "p_period_key": voice_minutes.period_key(), "p_delta": 90, "p_limit": 3600},
    ]
    assert data["consumedSeconds"] == 90
    assert data["monthlyRemainingSeconds"] == 410
    # The lesson has 510 s of its own left; the month's 410 is what counts.
    assert data["remainingSeconds"] == 410
    assert data["expired"] is False


def test_month_left_shorter_than_the_lesson_caps_the_countdown(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="starter_monthly", month_consumed=3600 - 120)
    mock_transport(handler)
    data = client.get("/api/users/me/lessons/L1/time", headers=auth_headers).json()
    assert (data["remainingSeconds"], data["monthlyRemainingSeconds"], data["expired"]) == (120, 120, False)


def test_spent_month_expires_the_lesson_with_the_month_reason(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="starter_monthly", lesson_consumed=60, month_consumed=3600)
    mock_transport(handler)
    data = client.get("/api/users/me/lessons/L1/time", headers=auth_headers).json()
    assert data["expired"] is True
    assert data["expiredReason"] == "month"
    assert data["remainingSeconds"] == 0


def test_month_wins_a_tie_with_the_lesson(client, auth_headers, mock_transport):
    # Both spent: "month" is what also closes the next lesson, so that is the reason given.
    handler, _ = _backend(plan_level="pro_monthly", lesson_consumed=600, month_consumed=7200)
    mock_transport(handler)
    data = client.get("/api/users/me/lessons/L1/time", headers=auth_headers).json()
    assert data["expiredReason"] == "month"


def test_spent_lesson_with_month_left_says_lesson(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="pro_monthly", lesson_consumed=600, month_consumed=600)
    mock_transport(handler)
    data = client.get("/api/users/me/lessons/L1/time", headers=auth_headers).json()
    assert (data["expired"], data["expiredReason"]) == (True, "lesson")


def test_first_beat_of_the_month_starts_a_row_for_this_account_only(client, auth_headers, mock_transport):
    # Last month's row and another learner's row this month must not count.
    month = voice_minutes.period_key()
    handler, state = _backend(plan_level="starter_monthly",
                              other_rows=[(USER_ID, "2020-01", 3600), (OTHER_USER, month, 3600)])
    mock_transport(handler)
    before = _minutes(client, auth_headers)
    assert (before["consumedSeconds"], before["expired"]) == (0, False)
    data = client.post("/api/users/me/lessons/L1/time/heartbeat", json={"deltaSeconds": 15},
                       headers=auth_headers).json()
    assert state["mine"]() == 15
    assert state["rows"][(OTHER_USER, month)] == 3600
    assert data["monthlyRemainingSeconds"] == 3585


def test_failed_add_reports_what_is_stored(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="starter_monthly", month_consumed=3000, rpc_fails=True)
    mock_transport(handler)
    data = client.post("/api/users/me/lessons/L1/time/heartbeat", json={"deltaSeconds": 15},
                       headers=auth_headers).json()
    # Not the full 60 minutes of a fail-open with nothing read: the 600 s really left.
    assert data["monthlyRemainingSeconds"] == 600


def test_trial_heartbeat_never_writes_the_pool(client, auth_headers, mock_transport):
    handler, state = _backend()
    mock_transport(handler)
    data = client.post("/api/users/me/lessons/L1/time/heartbeat", json={"deltaSeconds": 30},
                       headers=auth_headers).json()
    assert state["lesson"] == 30
    assert state["month_writes"] == []
    assert data["monthlyLimitSeconds"] is None
    assert data["monthlyRemainingSeconds"] is None


def test_activity_beats_from_old_site_clients_spend_the_month(client, auth_headers, mock_transport):
    handler, state = _backend(plan_level="pro_monthly", month_consumed=100)
    mock_transport(handler)
    res = client.post("/api/users/me/lessons/L1/activity", json={"deltaSeconds": 15}, headers=auth_headers)
    assert res.status_code == 200
    assert state["mine"]() == 115


def test_activity_that_fails_to_save_spends_nothing(client, auth_headers, mock_transport):
    # The client resends these seconds after the 503; spending them now would charge them twice.
    handler, state = _backend(plan_level="pro_monthly", month_consumed=100, lesson_write_fails=True)
    mock_transport(handler)
    res = client.post("/api/users/me/lessons/L1/activity", json={"deltaSeconds": 15}, headers=auth_headers)
    assert res.status_code == 503
    assert state["mine"]() == 100


def test_unreadable_pool_fails_open(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="starter_monthly", month_fails=True)
    mock_transport(handler)
    data = client.get("/api/users/me/lessons/L1/time", headers=auth_headers).json()
    assert data["expired"] is False
    assert data["remainingSeconds"] == 600


def test_unreadable_plan_never_blocks_the_lesson(client, auth_headers, mock_transport):
    handler, state = _backend(stripe_fails=True, month_consumed=99999)
    mock_transport(handler)
    data = client.post("/api/users/me/lessons/L1/time/heartbeat", json={"deltaSeconds": 15},
                       headers=auth_headers).json()
    assert data["expired"] is False
    assert state["month_writes"] == []


def test_site_lesson_session_refused_when_the_month_is_spent(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="starter_monthly", month_consumed=3600)
    openai = []

    def with_openai(request: httpx.Request) -> httpx.Response:
        if "client_secrets" in request.url.path:
            openai.append(1)
            return httpx.Response(200, json={"value": "ek_live_abc"})
        return handler(request)

    mock_transport(with_openai)
    res = client.post("/api/realtime/session", json={"mode": "lesson"}, headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "voice_minutes_exhausted"
    assert openai == []


def test_voice_minutes_requires_auth(client):
    assert client.get("/api/users/me/voice/minutes").status_code in (401, 403)


def test_lesson_access_sends_a_spent_month_to_the_exercises(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="starter_monthly", month_consumed=3600)
    mock_transport(handler)
    data = client.get("/api/users/me/guided-lesson/access?lessonId=fund-u1-l1", headers=auth_headers).json()
    assert (data["canStart"], data["reason"]) == (False, "month_spent")


def test_lesson_access_with_minutes_left_stays_open(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="starter_monthly", month_consumed=3599)
    mock_transport(handler)
    data = client.get("/api/users/me/guided-lesson/access?lessonId=fund-u1-l1", headers=auth_headers).json()
    assert (data["canStart"], data["reason"]) == (True, "subscriber")


def test_classroom_v2_gives_every_learner_ten_minutes(monkeypatch):
    # Paid was 15 minutes; since 2026-11-12 a lesson is 10 for everyone, admins keep an hour.
    import asyncio
    from unittest.mock import AsyncMock

    from app.services.classroom import service
    from app.services.user_data import SubscriptionInfo

    monkeypatch.setattr(service.conversation_credits, "is_admin", AsyncMock(return_value=False))
    for subscribed in (True, False):
        monkeypatch.setattr(service, "get_subscription", AsyncMock(return_value=SubscriptionInfo(isSubscribed=subscribed)))
        assert asyncio.run(service.budget("u")) == 600
    monkeypatch.setattr(service.conversation_credits, "is_admin", AsyncMock(return_value=True))
    assert asyncio.run(service.budget("u")) == 3600
