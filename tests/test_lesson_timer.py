"""Server-enforced per-lesson time budget (10 min free / 15 min paid)."""
import json

import httpx


def _free_subscription_handler(extra=None):
    """Build a MockTransport handler. `extra` lets a test inject lesson_time_usage
    behaviour; by default the user is free (no subscription row)."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "stripe_subscriptions" in path:
            return httpx.Response(200, json=[])  # free → 10 min
        if extra is not None and "lesson_time_usage" in path:
            return extra(request)
        if "lesson_time_usage" in path:
            return httpx.Response(200, json=[])  # no usage yet
        return httpx.Response(200, json=[])
    return handler


def test_free_plan_gets_ten_minute_budget(client, auth_headers, mock_transport):
    mock_transport(_free_subscription_handler())
    res = client.get("/api/users/me/lessons/beginner-01/time", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["limitSeconds"] == 600
    assert data["remainingSeconds"] == 600
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

    # Accumulates across heartbeats until the 10-min (600s) free budget is spent.
    for _ in range(6):
        r = client.post("/api/users/me/lessons/L1/time/heartbeat", json={"deltaSeconds": 90}, headers=auth_headers)
    assert state["consumed"] >= 600
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


def test_admin_lesson_time_is_unlimited(client, auth_headers, mock_transport):
    # Server-side twin of the session mint, which lets admins past the lesson budget: the app's
    # countdown must not end an admin's lesson either.
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "profiles" in path:
            return httpx.Response(200, json=[{"id": "u", "role": "admin"}])
        if "lesson_time_usage" in path:
            return httpx.Response(200, json=[{"id": "row-1", "consumed_seconds": 3600}])
        return httpx.Response(200, json=[])

    mock_transport(handler)
    status = client.get("/api/users/me/lessons/fund-u1-l2/time", headers=auth_headers).json()
    assert status["isUnlimited"] is True
    assert status["expired"] is False
    beat = client.post(
        "/api/users/me/lessons/fund-u1-l2/time/heartbeat", json={"deltaSeconds": 30}, headers=auth_headers,
    ).json()
    assert beat["isUnlimited"] is True
    assert beat["expired"] is False


def test_non_admin_status_says_limited(client, auth_headers, mock_transport):
    mock_transport(_free_subscription_handler())
    assert client.get("/api/users/me/lessons/beginner-01/time", headers=auth_headers).json()["isUnlimited"] is False


def _usage_store():
    """A one-row lesson_time_usage double that keeps what PATCH/POST write."""
    state = {"row": None, "writes": []}

    def usage(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[state["row"]] if state["row"] else [])
        body = json.loads(request.content or b"{}")
        state["writes"].append((request.method, body))
        state["row"] = {**(state["row"] or {"id": "row1", "consumed_seconds": 0, "active_seconds": 0}), **body}
        return httpx.Response(201 if request.method == "POST" else 200, json=[state["row"]])

    return state, usage


def test_activity_records_time_without_spending_the_budget(client, auth_headers, mock_transport):
    state, usage = _usage_store()
    mock_transport(_free_subscription_handler(usage))

    first = client.post("/api/users/me/lessons/L1/activity", json={"deltaSeconds": 15}, headers=auth_headers)
    assert first.status_code == 200
    assert first.json() == {"activeSeconds": 15}
    # First beat creates the row with an untouched budget.
    method, body = state["writes"][0]
    assert method == "POST"
    assert body["consumed_seconds"] == 0
    assert body["active_seconds"] == 15
    assert body["limit_seconds"] == 600

    # A forged 200 s beat is clamped to 90, and later beats only move active_seconds.
    second = client.post("/api/users/me/lessons/L1/activity", json={"deltaSeconds": 200}, headers=auth_headers)
    assert second.json() == {"activeSeconds": 105}
    method, body = state["writes"][1]
    assert method == "PATCH"
    assert "consumed_seconds" not in body
    assert body["active_seconds"] == 105

    budget = client.get("/api/users/me/lessons/L1/time", headers=auth_headers).json()
    assert budget["consumedSeconds"] == 0
    assert budget["remainingSeconds"] == 600


def test_activity_storage_error_is_an_error_so_the_client_retries(client, auth_headers, mock_transport):
    def usage(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(400, json={"message": 'column "active_seconds" does not exist'})

    mock_transport(_free_subscription_handler(usage))
    res = client.post("/api/users/me/lessons/L1/activity", json={"deltaSeconds": 15}, headers=auth_headers)
    assert res.status_code == 503


def test_activity_requires_auth(client):
    assert client.post("/api/users/me/lessons/L1/activity", json={"deltaSeconds": 10}).status_code in (401, 403)
