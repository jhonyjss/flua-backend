"""Free-conversation credit pool (daily limits by plan)."""
import json

import httpx


def _sub_handler(plan_level=None, status="active", usage=None):
    """MockTransport handler. `plan_level=None` → free (no subscription row).
    `usage` lets a test drive the conversation_credits table behaviour."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "stripe_subscriptions" in path:
            if plan_level is None:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{"status": status, "plan_level": plan_level}])
        if usage is not None and "conversation_credits" in path:
            return usage(request)
        if "conversation_credits" in path:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])
    return handler


def test_free_plan_gets_five_minutes_per_day(client, auth_headers, mock_transport):
    mock_transport(_sub_handler())
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["limitSeconds"] == 300
    assert data["remainingSeconds"] == 300
    assert data["expired"] is False
    assert data["isFree"] is True
    assert data["periodLabel"] == "dia"


def test_starter_plan_gets_ten_minutes_per_day(client, auth_headers, mock_transport):
    mock_transport(_sub_handler(plan_level="starter"))
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["limitSeconds"] == 10 * 60
    assert data["isFree"] is False
    assert data["periodLabel"] == "dia"


def test_pro_plan_gets_thirty_minutes_per_day(client, auth_headers, mock_transport):
    mock_transport(_sub_handler(plan_level="pro_yearly"))  # suffixed level still maps to pro
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["limitSeconds"] == 30 * 60


def test_premium_plan_gets_sixty_minutes_per_day(client, auth_headers, mock_transport):
    mock_transport(_sub_handler(plan_level="premium_monthly"))
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["limitSeconds"] == 60 * 60


def test_heartbeat_accumulates_clamps_and_expires_for_free(client, auth_headers, mock_transport):
    state = {"consumed": 0, "exists": False}

    def usage(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            rows = [{"id": "row1", "consumed_seconds": state["consumed"]}] if state["exists"] else []
            return httpx.Response(200, json=rows)
        body = json.loads(request.content or b"{}")
        state["consumed"] = int(body.get("consumed_seconds", state["consumed"]))
        state["exists"] = True
        return httpx.Response(201 if request.method == "POST" else 200, json=[{"id": "row1"}])

    mock_transport(_sub_handler(usage=usage))

    # A forged 500s delta is clamped to the 90s max.
    r1 = client.post("/api/users/me/conversation/time/heartbeat", json={"deltaSeconds": 500}, headers=auth_headers)
    assert r1.json()["consumedSeconds"] == 90
    assert r1.json()["expired"] is False

    # Accumulates until the 5-min (300s) daily free budget is spent.
    for _ in range(3):
        r = client.post("/api/users/me/conversation/time/heartbeat", json={"deltaSeconds": 90}, headers=auth_headers)
    assert state["consumed"] >= 300
    assert r.json()["expired"] is True
    assert r.json()["remainingSeconds"] == 0


def test_conversation_endpoints_require_auth(client):
    assert client.get("/api/users/me/conversation/time").status_code in (401, 403)
    assert client.post(
        "/api/users/me/conversation/time/heartbeat", json={"deltaSeconds": 10},
    ).status_code in (401, 403)


def test_status_fails_open_when_table_unreadable(client, auth_headers, mock_transport):
    def usage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="relation does not exist")

    mock_transport(_sub_handler(usage=usage))
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    # Infra error must not block the student — permissive status returned.
    assert res.status_code == 200
    assert res.json()["expired"] is False
