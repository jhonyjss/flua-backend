"""Free conversation ("conversa livre") was removed from every plan on 2026-11-12 (owner decision).

Every non-admin account gets a locked status, so apps built before the removal show it as
unavailable; heartbeats from those apps are answered and spend nothing. The table now holds the
month's pool of Flua minutes (tests/test_voice_minutes.py).
"""
import httpx


def _sub_handler(plan_level=None, status="active", usage=None, role="student"):
    """MockTransport handler. `plan_level=None` → free (no subscription row). `usage` answers the
    conversation_credits table."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "stripe_subscriptions" in path:
            if plan_level is None:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{"status": status, "plan_level": plan_level}])
        if "profiles" in path:
            return httpx.Response(200, json=[{"id": "u", "role": role}])
        if usage is not None and "conversation_credits" in path:
            return usage(request)
        return httpx.Response(200, json=[])
    return handler


LOCKED = {
    "limitSeconds": 0, "consumedSeconds": 0, "remainingSeconds": 0, "expired": True,
    "isUnlimited": False, "periodLabel": "indisponível",
}


def test_every_plan_gets_a_locked_conversation(client, auth_headers, mock_transport):
    for plan, label in ((None, "free"), ("starter_monthly", "starter"), ("pro_yearly", "pro"),
                        ("premium_monthly", "premium")):
        mock_transport(_sub_handler(plan_level=plan))
        res = client.get("/api/users/me/conversation/time", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == {**LOCKED, "planLevel": label, "isFree": plan is None}, plan


def test_old_app_heartbeats_spend_nothing(client, auth_headers, mock_transport):
    def usage(request: httpx.Request) -> httpx.Response:
        raise AssertionError("free conversation must not read or write conversation_credits")

    mock_transport(_sub_handler(plan_level="starter_monthly", usage=usage))
    res = client.post("/api/users/me/conversation/time/heartbeat", json={"deltaSeconds": 90}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {**LOCKED, "planLevel": "starter", "isFree": False}


def test_unreadable_plan_is_still_locked(client, auth_headers, mock_transport):
    def handler(request: httpx.Request) -> httpx.Response:
        if "stripe_subscriptions" in request.url.path:
            return httpx.Response(500, json={"message": "down"})
        return httpx.Response(200, json=[])

    mock_transport(handler)
    data = client.get("/api/users/me/conversation/time", headers=auth_headers).json()
    assert data["expired"] is True
    assert data["isUnlimited"] is False


def test_conversation_endpoints_require_auth(client):
    assert client.get("/api/users/me/conversation/time").status_code in (401, 403)
    assert client.post(
        "/api/users/me/conversation/time/heartbeat", json={"deltaSeconds": 10},
    ).status_code in (401, 403)


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


def test_admin_gets_unlimited_conversation_without_a_subscription(client, auth_headers, mock_transport):
    """Admins have no Stripe row but must not be locked out (parity with the site's isAdmin)."""
    mock_transport(_sub_handler(plan_level=None, role="admin"))
    data = client.get("/api/users/me/conversation/time", headers=auth_headers).json()
    assert data["isUnlimited"] is True
    assert data["expired"] is False
    assert data["planLevel"] == "premium"
