"""In-app purchases through RevenueCat: the webhook, the state read from RevenueCat's API, and how it
joins Stripe in get_subscription (so the plan is the same on the site and in the app)."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.services import revenuecat

USER = "00000000-0000-0000-0000-000000000001"
SECRET = "Bearer rc-webhook-secret"


@pytest.fixture(autouse=True)
def revenuecat_env(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("REVENUECAT_SECRET_KEY", "sk_rc_test")
    monkeypatch.setenv("REVENUECAT_WEBHOOK_AUTH", SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _iso(delta_days: float) -> str:
    return (datetime.now(UTC) + timedelta(days=delta_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def subscriber(entitlements: dict, subscriptions: dict) -> dict:
    return {"subscriber": {"entitlements": entitlements, "subscriptions": subscriptions}}


PRO_MONTHLY = subscriber(
    {"pro": {"expires_date": _iso(20), "product_identifier": "flueai_pro_monthly", "purchase_date": _iso(-10)}},
    {"flueai_pro_monthly": {
        "store": "app_store", "period_type": "normal", "expires_date": _iso(20),
        "unsubscribe_detected_at": None, "billing_issues_detected_at": None,
    }},
)


# ── Pure mapping ──────────────────────────────────────────────────────────────


def test_active_pro_entitlement_becomes_a_pro_plan():
    state = revenuecat.state_from_subscriber(PRO_MONTHLY["subscriber"])
    assert state["entitlement"] == "pro"
    assert state["product_id"] == "flueai_pro_monthly"
    assert state["store"] == "app_store"
    assert state["will_renew"] is True
    assert state["billing_issue"] is False
    info = revenuecat.subscription_info(state)
    assert info.isSubscribed is True
    assert info.planLevel == "pro_monthly"
    assert info.status == "active"
    assert info.cancelAtPeriodEnd is False
    assert info.source == "app_store"


def test_pro_wins_over_starter_and_yearly_products_say_so():
    sub = subscriber(
        {
            "starter": {"expires_date": _iso(5), "product_identifier": "flueai_starter_monthly"},
            "pro": {"expires_date": _iso(300), "product_identifier": "flueai_pro_yearly"},
        },
        {"flueai_pro_yearly": {"store": "play_store", "period_type": "trial", "expires_date": _iso(300),
                               "unsubscribe_detected_at": _iso(-1), "billing_issues_detected_at": None}},
    )
    state = revenuecat.state_from_subscriber(sub["subscriber"])
    info = revenuecat.subscription_info(state)
    assert info.planLevel == "pro_yearly"
    assert info.status == "trialing"
    assert info.cancelAtPeriodEnd is True  # unsubscribed: runs to the end of the period
    assert info.source == "play_store"


def test_expired_entitlement_is_not_a_subscription():
    sub = subscriber({"pro": {"expires_date": _iso(-1), "product_identifier": "flueai_pro_monthly"}}, {})
    state = revenuecat.state_from_subscriber(sub["subscriber"])
    assert state["entitlement"] is None
    assert revenuecat.subscription_info(state).isSubscribed is False


def test_grace_period_keeps_the_plan_and_reports_the_billing_issue():
    sub = subscriber(
        {"starter": {"expires_date": _iso(-1), "grace_period_expires_date": _iso(3),
                     "product_identifier": "flueai_starter_monthly"}},
        {"flueai_starter_monthly": {"store": "app_store", "period_type": "normal", "expires_date": _iso(-1),
                                    "unsubscribe_detected_at": None, "billing_issues_detected_at": _iso(-1)}},
    )
    info = revenuecat.subscription_info(revenuecat.state_from_subscriber(sub["subscriber"]))
    assert info.isSubscribed is True
    assert info.planLevel == "starter_monthly"
    assert info.status == "past_due"


# ── Webhook ───────────────────────────────────────────────────────────────────


def _rc_backend(answer=PRO_MONTHLY, status=200, calls=None, stripe_rows=()):
    log = calls if calls is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.revenuecat.com" in url:
            log.append(("rc", request.method, url, request.headers.get("authorization")))
            return httpx.Response(status, json=answer)
        path = request.url.path
        if path.endswith("/app_store_subscriptions"):
            log.append(("upsert", request.method, json.loads(request.content) if request.content else None))
            return httpx.Response(201, json=[])
        if path.endswith("/stripe_subscriptions"):
            return httpx.Response(200, json=list(stripe_rows))
        return httpx.Response(200, json=[])

    return handler


def _event(**patch):
    return {"api_version": "1.0", "event": {"id": "evt_1", "type": "INITIAL_PURCHASE", "app_user_id": USER, **patch}}


def test_webhook_refuses_a_wrong_secret(client, mock_transport):
    calls = []
    mock_transport(_rc_backend(calls=calls))
    res = client.post("/api/revenuecat/webhook", json=_event(), headers={"Authorization": "Bearer nope"})
    assert res.status_code == 401
    assert calls == []


def test_webhook_refreshes_the_buyer_from_revenuecat(client, mock_transport):
    calls = []
    mock_transport(_rc_backend(calls=calls))
    res = client.post("/api/revenuecat/webhook", json=_event(), headers={"Authorization": SECRET})
    assert res.status_code == 200
    rc = [c for c in calls if c[0] == "rc"]
    assert rc == [("rc", "GET", f"https://api.revenuecat.com/v1/subscribers/{USER}", "Bearer sk_rc_test")]
    saved = next(c[2] for c in calls if c[0] == "upsert")
    assert saved["user_id"] == USER
    assert saved["entitlement"] == "pro"
    assert saved["product_id"] == "flueai_pro_monthly"
    assert saved["last_event_id"] == "evt_1"


def test_webhook_transfer_refreshes_the_receiving_account(client, mock_transport):
    calls = []
    mock_transport(_rc_backend(calls=calls))
    other = "00000000-0000-0000-0000-000000000002"
    body = _event(type="TRANSFER", app_user_id="$RCAnonymousID:abc", transferred_from=[USER], transferred_to=[other])
    assert client.post("/api/revenuecat/webhook", json=body, headers={"Authorization": SECRET}).status_code == 200
    assert [c[2].rsplit("/", 1)[-1] for c in calls if c[0] == "rc"] == [other]


def test_webhook_ignores_anonymous_buyers_and_test_events(client, mock_transport):
    calls = []
    mock_transport(_rc_backend(calls=calls))
    anon = _event(app_user_id="$RCAnonymousID:abc")
    assert client.post("/api/revenuecat/webhook", json=anon, headers={"Authorization": SECRET}).status_code == 200
    test = _event(type="TEST")
    assert client.post("/api/revenuecat/webhook", json=test, headers={"Authorization": SECRET}).status_code == 200
    assert calls == []


def test_webhook_asks_for_a_retry_when_revenuecat_is_down(client, mock_transport):
    mock_transport(_rc_backend(status=503))
    assert client.post("/api/revenuecat/webhook", json=_event(), headers={"Authorization": SECRET}).status_code == 502


# ── Sync from the app, right after a purchase ─────────────────────────────────


def test_app_sync_returns_the_new_plan(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_rc_backend(calls=calls))
    res = client.post("/api/revenuecat/sync", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["isSubscribed"] is True
    assert res.json()["planLevel"] == "pro_monthly"
    assert res.json()["source"] == "app_store"
    assert any(c[0] == "upsert" for c in calls)


def test_sync_needs_a_session(client):
    assert client.post("/api/revenuecat/sync").status_code == 401


# ── One plan per account: Stripe and the stores together ──────────────────────


def _subscription_backend(*, stripe_rows=(), store_row=None):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/stripe_subscriptions"):
            return httpx.Response(200, json=list(stripe_rows))
        if path.endswith("/app_store_subscriptions"):
            return httpx.Response(200, json=[] if store_row is None else [store_row])
        return httpx.Response(200, json=[])

    return handler


STORE_ROW = {
    "user_id": USER, "entitlement": "starter", "product_id": "flueai_starter_monthly", "store": "app_store",
    "period_type": "normal", "expires_at": _iso(10), "will_renew": True, "billing_issue": False,
}


def test_app_store_subscriber_counts_on_the_site(client, auth_headers, mock_transport):
    mock_transport(_subscription_backend(store_row=STORE_ROW))
    body = client.get("/api/users/me/subscription", headers=auth_headers).json()
    assert body["isSubscribed"] is True
    assert body["planLevel"] == "starter_monthly"
    assert body["source"] == "app_store"


def test_the_higher_plan_wins_when_both_are_active(client, auth_headers, mock_transport):
    stripe = [{"status": "active", "plan_name": "pro_monthly"}]
    mock_transport(_subscription_backend(stripe_rows=stripe, store_row=STORE_ROW))
    body = client.get("/api/users/me/subscription", headers=auth_headers).json()
    assert body["planLevel"] == "pro_monthly"
    assert body["source"] == "stripe"


def test_an_expired_store_row_does_not_count(client, auth_headers, mock_transport):
    mock_transport(_subscription_backend(store_row={**STORE_ROW, "expires_at": _iso(-2)}))
    assert client.get("/api/users/me/subscription", headers=auth_headers).json()["isSubscribed"] is False


def test_store_subscriber_gets_the_free_conversation(client, auth_headers, mock_transport):
    pro_row = {**STORE_ROW, "entitlement": "pro", "product_id": "flueai_pro_monthly"}
    mock_transport(_subscription_backend(store_row=pro_row))
    status = client.get("/api/users/me/conversation/time", headers=auth_headers).json()
    assert status["isUnlimited"] is True


def test_an_unreadable_store_table_leaves_the_stripe_plan(client, auth_headers, mock_transport):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/stripe_subscriptions"):
            return httpx.Response(200, json=[{"status": "active", "plan_name": "starter_monthly"}])
        if path.endswith("/app_store_subscriptions"):
            return httpx.Response(500, json={"message": "down"})
        return httpx.Response(200, json=[])

    mock_transport(handler)
    res = client.get("/api/users/me/subscription", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["planLevel"] == "starter_monthly"
