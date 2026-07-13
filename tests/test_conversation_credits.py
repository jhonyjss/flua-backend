"""Free-conversation credit pool (free weekly, starter daily, pro unlimited).

Paid-only strategy: a *new* (non-legacy) free account gets 0 free seconds.
Pre-cutover accounts keep the weekly free minutes only during the legacy grace
window (LEGACY_GRACE_ENDS_AT). Legacy tests freeze that deadline into the future
so they don't become date-dependent after the real grace ends.
"""
import datetime as dt
import json

import httpx

from app.services import conversation_credits as cc

FAR_FUTURE = dt.datetime(2999, 1, 1, tzinfo=dt.timezone.utc)


def _sub_handler(plan_level=None, status="active", usage=None, legacy=False):
    """MockTransport handler. `plan_level=None` → free (no subscription row).
    `usage` lets a test drive the conversation_credits table behaviour.
    `legacy` sets profiles.legacy_free_access for the grace-window check."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "stripe_subscriptions" in path:
            if plan_level is None:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{"status": status, "plan_level": plan_level}])
        if "profiles" in path:
            return httpx.Response(200, json=[{"id": "u", "legacy_free_access": legacy}])
        if usage is not None and "conversation_credits" in path:
            return usage(request)
        if "conversation_credits" in path:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])
    return handler


def test_new_free_account_gets_no_conversation(client, auth_headers, mock_transport):
    """Paid-only: a non-legacy free account has no free conversation minutes."""
    mock_transport(_sub_handler())  # free, legacy=False
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["limitSeconds"] == 0
    assert data["remainingSeconds"] == 0
    assert data["expired"] is True
    assert data["isFree"] is True
    assert data["isUnlimited"] is False
    assert data["periodLabel"] == "semana"


def test_legacy_free_gets_five_minutes_within_grace(client, auth_headers, mock_transport, monkeypatch):
    """Grandfathered accounts keep 5 min/week, but only inside the grace window."""
    monkeypatch.setattr(cc, "LEGACY_GRACE_ENDS_AT", FAR_FUTURE)
    mock_transport(_sub_handler(legacy=True))
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["limitSeconds"] == 300
    assert data["remainingSeconds"] == 300
    assert data["expired"] is False
    assert data["isFree"] is True
    assert data["periodLabel"] == "semana"


def test_legacy_free_locked_after_grace(client, auth_headers, mock_transport, monkeypatch):
    """After the grace deadline even legacy accounts get 0 — nothing is free."""
    monkeypatch.setattr(cc, "LEGACY_GRACE_ENDS_AT", dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc))
    mock_transport(_sub_handler(legacy=True))
    data = client.get("/api/users/me/conversation/time", headers=auth_headers).json()
    assert data["limitSeconds"] == 0
    assert data["expired"] is True


def test_starter_plan_gets_ten_minutes_per_day(client, auth_headers, mock_transport):
    mock_transport(_sub_handler(plan_level="starter"))
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["limitSeconds"] == 10 * 60
    assert data["isFree"] is False
    assert data["isUnlimited"] is False
    assert data["periodLabel"] == "dia"


def test_pro_plan_gets_unlimited_conversation(client, auth_headers, mock_transport):
    mock_transport(_sub_handler(plan_level="pro_yearly"))  # suffixed level still maps to pro
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["limitSeconds"] == 0
    assert data["remainingSeconds"] == 0
    assert data["expired"] is False
    assert data["isUnlimited"] is True
    assert data["periodLabel"] == "livre"


def test_premium_plan_gets_unlimited_conversation(client, auth_headers, mock_transport):
    mock_transport(_sub_handler(plan_level="premium_monthly"))
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["isUnlimited"] is True


def test_heartbeat_accumulates_clamps_and_expires_for_free(client, auth_headers, mock_transport, monkeypatch):
    # Exercise the 5-min weekly free budget via a grandfathered account inside grace.
    monkeypatch.setattr(cc, "LEGACY_GRACE_ENDS_AT", FAR_FUTURE)
    state = {"consumed": 0, "exists": False}

    def usage(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            rows = [{"id": "row1", "consumed_seconds": state["consumed"]}] if state["exists"] else []
            return httpx.Response(200, json=rows)
        body = json.loads(request.content or b"{}")
        state["consumed"] = int(body.get("consumed_seconds", state["consumed"]))
        state["exists"] = True
        return httpx.Response(201 if request.method == "POST" else 200, json=[{"id": "row1"}])

    mock_transport(_sub_handler(usage=usage, legacy=True))

    # A forged 500s delta is clamped to the 90s max.
    r1 = client.post("/api/users/me/conversation/time/heartbeat", json={"deltaSeconds": 500}, headers=auth_headers)
    assert r1.json()["consumedSeconds"] == 90
    assert r1.json()["expired"] is False

    # Accumulates until the 5-min (300s) weekly free budget is spent.
    for _ in range(3):
        r = client.post("/api/users/me/conversation/time/heartbeat", json={"deltaSeconds": 90}, headers=auth_headers)
    assert state["consumed"] >= 300
    assert r.json()["expired"] is True
    assert r.json()["remainingSeconds"] == 0


def test_heartbeat_does_not_track_pro_usage(client, auth_headers, mock_transport):
    def usage(request: httpx.Request) -> httpx.Response:
        raise AssertionError("unlimited plans must not read or write conversation_credits")

    mock_transport(_sub_handler(plan_level="pro", usage=usage))
    res = client.post("/api/users/me/conversation/time/heartbeat", json={"deltaSeconds": 90}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["isUnlimited"] is True
    assert data["expired"] is False


def test_conversation_endpoints_require_auth(client):
    assert client.get("/api/users/me/conversation/time").status_code in (401, 403)
    assert client.post(
        "/api/users/me/conversation/time/heartbeat", json={"deltaSeconds": 10},
    ).status_code in (401, 403)


def test_status_fails_open_when_table_unreadable(client, auth_headers, mock_transport, monkeypatch):
    monkeypatch.setattr(cc, "LEGACY_GRACE_ENDS_AT", FAR_FUTURE)

    def usage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="relation does not exist")

    # An entitled user (legacy, in grace) whose usage table is unreadable must
    # NOT be blocked by the infra error — permissive status returned.
    mock_transport(_sub_handler(usage=usage, legacy=True))
    res = client.get("/api/users/me/conversation/time", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["expired"] is False


# ── Regression: paid users were shown as "free" ──────────────────────────


def test_map_subscription_derives_plan_level_from_plan_name():
    """The table has no plan_level/plan column — only plan_name. Without the
    fallback, planLevel was always None and every paid user became 'free'."""
    from app.services.user_data import map_subscription

    info = map_subscription({"status": "active", "plan_name": "starter_monthly"})
    assert info.isSubscribed is True
    assert info.planLevel == "starter_monthly"  # feeds _base_plan → "starter", not "free"


def test_base_plan_maps_suffixed_plan_name_to_tier():
    from app.services.conversation_credits import _base_plan

    assert _base_plan("starter_monthly", True) == "starter"
    assert _base_plan("pro_yearly", True) == "pro"
    assert _base_plan(None, True) == "free"          # missing level → free
    assert _base_plan("starter_monthly", False) == "free"  # not subscribed → free
