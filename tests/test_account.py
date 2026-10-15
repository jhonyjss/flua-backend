"""DELETE /api/users/me: Stripe → Storage → Auth, and a Stripe failure stops everything."""
import httpx
import pytest

from app.services import stripe_service

USER = "00000000-0000-0000-0000-000000000001"


@pytest.fixture()
def stripe_calls(monkeypatch):
    calls = []

    def cancel(customer_id, *, immediately=False):
        calls.append((customer_id, immediately))
        return True

    monkeypatch.setattr(stripe_service, "cancel_subscription", cancel)
    return calls


def _supabase(*, customer="cus_123", files=("avatar_1.png",), storage_fails=False, auth_status=200, calls=None):
    log = calls if calls is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "api.revenuecat.com" in str(request.url):
            log.append(("revenuecat", f"{request.method} {path}"))
            return httpx.Response(200, json={})
        if path.endswith("/stripe_customers"):
            return httpx.Response(200, json=[] if customer is None else [{"stripe_customer_id": customer}])
        if "/storage/v1/object/list/avatars" in path:
            log.append(("list", request.content.decode()))
            if storage_fails:
                return httpx.Response(500, json={"message": "down"})
            return httpx.Response(200, json=[{"name": name} for name in files])
        if path.endswith("/storage/v1/object/avatars") and request.method == "DELETE":
            log.append(("remove", request.content.decode()))
            return httpx.Response(200, json=[])
        if f"/auth/v1/admin/users/{USER}" in path and request.method == "DELETE":
            log.append(("auth", path))
            return httpx.Response(auth_status, json={})
        return httpx.Response(200, json=[])

    return handler


def _kinds(calls):
    return [kind for kind, _ in calls]


def test_deletes_subscription_files_and_login_in_that_order(client, auth_headers, mock_transport, stripe_calls):
    calls = []
    mock_transport(_supabase(calls=calls))
    res = client.delete("/api/users/me", headers=auth_headers)
    assert res.status_code == 204
    assert stripe_calls == [("cus_123", True)]  # cancelled now, not at period end
    assert _kinds(calls) == ["list", "remove", "auth"]
    assert f"profile/user/{USER}/" in calls[0][1]
    assert f"profile/user/{USER}/avatar_1.png" in calls[1][1]


def test_without_stripe_customer_or_files_it_just_deletes_the_login(client, auth_headers, mock_transport, stripe_calls):
    calls = []
    mock_transport(_supabase(customer=None, files=(), calls=calls))
    assert client.delete("/api/users/me", headers=auth_headers).status_code == 204
    assert stripe_calls == []
    assert _kinds(calls) == ["list", "auth"]


def test_a_stripe_failure_keeps_the_account(client, auth_headers, mock_transport, monkeypatch):
    calls = []

    def broken(customer_id, *, immediately=False):
        raise RuntimeError("stripe down")

    monkeypatch.setattr(stripe_service, "cancel_subscription", broken)
    mock_transport(_supabase(calls=calls))
    res = client.delete("/api/users/me", headers=auth_headers)
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "billing_unavailable"
    assert "auth" not in _kinds(calls)


def test_a_leftover_avatar_does_not_keep_the_account(client, auth_headers, mock_transport, stripe_calls):
    calls = []
    mock_transport(_supabase(storage_fails=True, calls=calls))
    assert client.delete("/api/users/me", headers=auth_headers).status_code == 204
    assert _kinds(calls)[-1] == "auth"


def test_an_auth_failure_is_reported(client, auth_headers, mock_transport, stripe_calls):
    mock_transport(_supabase(auth_status=500))
    assert client.delete("/api/users/me", headers=auth_headers).status_code == 502


def test_deleting_needs_a_session(client):
    assert client.delete("/api/users/me").status_code == 401


def test_the_purchase_history_in_revenuecat_goes_too(client, auth_headers, mock_transport, stripe_calls, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("REVENUECAT_SECRET_KEY", "sk_rc_test")
    get_settings.cache_clear()
    calls = []
    mock_transport(_supabase(calls=calls))
    assert client.delete("/api/users/me", headers=auth_headers).status_code == 204
    assert ("revenuecat", f"DELETE /v1/subscribers/{USER}") in calls
    assert _kinds(calls)[-1] == "auth"  # the login is the last thing removed
