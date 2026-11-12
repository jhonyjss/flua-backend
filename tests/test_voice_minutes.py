"""The month's pool of Flua voice minutes (owner decision 2026-11-12): 60 min Starter, 120 min Pro,
spent by lessons with Flua; free trial lessons and admins never touch it."""
import datetime as dt
import json

import httpx

from app.services import voice_minutes


def _backend(*, plan_level=None, role="student", lesson_consumed=0, month_consumed=0,
             month_fails=False, stripe_fails=False):
    """Supabase as seen from the backend, with the two usage tables kept in memory.

    Returns (handler, state): state["lesson"] / state["month"] hold consumed seconds, and
    state["month_writes"] every write body sent to conversation_credits."""
    state = {"lesson": lesson_consumed, "month": month_consumed, "month_writes": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "stripe_subscriptions" in path:
            if stripe_fails:
                return httpx.Response(500, json={"message": "down"})
            rows = [] if plan_level is None else [{"status": "active", "plan_level": plan_level}]
            return httpx.Response(200, json=rows)
        if "profiles" in path:
            return httpx.Response(200, json=[{"id": "u", "role": role}])
        if "conversation_credits" in path:
            if month_fails:
                return httpx.Response(500, json={"message": "down"})
            if request.method == "GET":
                rows = [{"id": "m1", "consumed_seconds": state["month"]}] if state["month"] else []
                return httpx.Response(200, json=rows)
            body = json.loads(request.content or b"{}")
            state["month_writes"].append(body)
            state["month"] = body["consumed_seconds"]
            return httpx.Response(201 if request.method == "POST" else 200, json=[{"id": "m1"}])
        if "lesson_time_usage" in path:
            if request.method == "GET":
                rows = [{"id": "l1", "consumed_seconds": state["lesson"], "active_seconds": 0}] if state["lesson"] else []
                return httpx.Response(200, json=rows)
            body = json.loads(request.content or b"{}")
            state["lesson"] = body.get("consumed_seconds", state["lesson"])
            return httpx.Response(201 if request.method == "POST" else 200, json=[{"id": "l1"}])
        return httpx.Response(200, json=[])

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
    assert data["periodKey"] == voice_minutes.period_key()
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
    assert state["month"] == 3190
    assert state["month_writes"][0]["limit_seconds"] == 3600
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


def test_spent_lesson_says_lesson_even_with_the_month_spent(client, auth_headers, mock_transport):
    handler, _ = _backend(plan_level="pro_monthly", lesson_consumed=600, month_consumed=7200)
    mock_transport(handler)
    data = client.get("/api/users/me/lessons/L1/time", headers=auth_headers).json()
    assert data["expiredReason"] == "lesson"


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
    assert state["month"] == 115


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
