"""Server-enforced per-lesson time budget (5 min free / 15 min paid)."""
import json

import httpx


def _free_subscription_handler(extra=None):
    """Build a MockTransport handler. `extra` lets a test inject lesson_time_usage
    behaviour; by default the user is free (no subscription row)."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "stripe_subscriptions" in path:
            return httpx.Response(200, json=[])  # free → 5 min
        if extra is not None and "lesson_time_usage" in path:
            return extra(request)
        if "lesson_time_usage" in path:
            return httpx.Response(200, json=[])  # no usage yet
        return httpx.Response(200, json=[])
    return handler


def test_free_plan_gets_five_minute_budget(client, auth_headers, mock_transport):
    mock_transport(_free_subscription_handler())
    res = client.get("/api/users/me/lessons/beginner-01/time", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["limitSeconds"] == 300
    assert data["remainingSeconds"] == 300
    assert data["expired"] is False


def test_paid_plan_gets_fifteen_minute_budget(client, auth_headers, mock_transport):
    def handler(request: httpx.Request) -> httpx.Response:
        if "stripe_subscriptions" in request.url.path:
            return httpx.Response(200, json=[{"status": "active", "plan_level": "pro"}])
        return httpx.Response(200, json=[])

    mock_transport(handler)
    res = client.get("/api/users/me/lessons/beginner-01/time", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["limitSeconds"] == 900


def test_heartbeat_accumulates_clamps_and_expires(client, auth_headers, mock_transport):
    state = {"consumed": 0, "exists": False}

    def usage(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            rows = [{"id": "row1", "consumed_seconds": state["consumed"]}] if state["exists"] else []
            return httpx.Response(200, json=rows)
        body = json.loads(request.content or b"{}")
        state["consumed"] = int(body.get("consumed_seconds", state["consumed"]))
        state["exists"] = True
        return httpx.Response(201 if request.method == "POST" else 200, json=[{"id": "row1"}])

    mock_transport(_free_subscription_handler(usage))

    # A forged 200s delta is clamped to the 90s max.
    r1 = client.post("/api/users/me/lessons/L1/time/heartbeat", json={"deltaSeconds": 200}, headers=auth_headers)
    assert r1.json()["consumedSeconds"] == 90
    assert r1.json()["expired"] is False

    # Accumulates across heartbeats until the 5-min (300s) free budget is spent.
    for _ in range(3):
        r = client.post("/api/users/me/lessons/L1/time/heartbeat", json={"deltaSeconds": 90}, headers=auth_headers)
    assert state["consumed"] >= 300
    assert r.json()["expired"] is True
    assert r.json()["remainingSeconds"] == 0


def test_time_endpoints_require_auth(client):
    assert client.get("/api/users/me/lessons/L1/time").status_code in (401, 403)
    assert client.post("/api/users/me/lessons/L1/time/heartbeat", json={"deltaSeconds": 10}).status_code in (401, 403)


def test_status_fails_open_when_usage_table_unreadable(client, auth_headers, mock_transport):
    def usage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="relation does not exist")

    mock_transport(_free_subscription_handler(usage))
    res = client.get("/api/users/me/lessons/L1/time", headers=auth_headers)
    # Infra error must not lock the student out — permissive status returned.
    assert res.status_code == 200
    assert res.json()["expired"] is False
