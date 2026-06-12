from unittest.mock import patch

import httpx


def supabase_handler(rows: list[dict]):
    """MockTransport handler for the Supabase REST customer lookup."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "rest/v1/stripe_customers" in str(request.url):
            if request.method == "GET":
                return httpx.Response(200, json=rows)
            return httpx.Response(201, json=rows or [{}])
        raise AssertionError(f"unexpected call: {request.url}")

    return handler


def test_checkout_requires_auth(client):
    res = client.post("/api/stripe/create-checkout-session", json={"planName": "pro"})
    assert res.status_code == 401


def test_checkout_validates_plan(client, auth_headers):
    res = client.post(
        "/api/stripe/create-checkout-session",
        json={"planName": "platinum"},
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_checkout_creates_session_for_existing_customer(client, auth_headers, mock_transport):
    mock_transport(supabase_handler([{"stripe_customer_id": "cus_123"}]))

    with (
        patch("app.services.stripe_service.customer_exists", return_value=True),
        patch(
            "app.services.stripe_service.create_checkout_session",
            return_value=("https://checkout.stripe.com/s/123", "cs_123"),
        ) as create,
    ):
        res = client.post(
            "/api/stripe/create-checkout-session",
            json={"planName": "pro", "billing": "yearly"},
            headers=auth_headers,
        )

    assert res.status_code == 200
    assert res.json() == {"url": "https://checkout.stripe.com/s/123", "sessionId": "cs_123"}
    assert create.call_args.kwargs["price_id"] == "price_pro_y"
    assert create.call_args.kwargs["customer_id"] == "cus_123"


def test_checkout_missing_price_id_returns_500(client, auth_headers, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("STRIPE_PRICE_PRO_MONTHLY", "")
    get_settings.cache_clear()
    res = client.post(
        "/api/stripe/create-checkout-session",
        json={"planName": "pro", "billing": "monthly"},
        headers=auth_headers,
    )
    assert res.status_code == 500
    assert "STRIPE_PRICE_PRO_MONTHLY" in res.json()["detail"]


def test_portal_404_without_customer(client, auth_headers, mock_transport):
    mock_transport(supabase_handler([]))
    res = client.post("/api/stripe/create-portal-session", headers=auth_headers)
    assert res.status_code == 404


def test_invoices_empty_without_customer(client, auth_headers, mock_transport):
    mock_transport(supabase_handler([]))
    res = client.get("/api/stripe/get-invoices", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"invoices": []}


def test_webhook_rejects_bad_signature(client):
    res = client.post(
        "/api/stripe/webhook",
        content=b"{}",
        headers={"stripe-signature": "t=1,v1=bad"},
    )
    assert res.status_code == 400


def test_webhook_accepts_valid_signature(client):
    import json
    import time
    import hmac
    import hashlib

    payload = json.dumps({"id": "evt_1", "object": "event", "type": "invoice.payment_succeeded", "data": {"object": {}}, "api_version": "2024-06-20"}).encode()
    ts = int(time.time())
    signed = hmac.new(b"whsec_test", f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    res = client.post(
        "/api/stripe/webhook",
        content=payload,
        headers={"stripe-signature": f"t={ts},v1={signed}"},
    )
    assert res.status_code == 200
    assert res.json() == {"received": True}
