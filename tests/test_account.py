"""DELETE /api/users/me: Stripe → Storage → Auth, a Stripe failure stops everything, and it can be repeated.

Both providers are faked where the process ends, at HTTP: Supabase at the httpx transport, Stripe at the
SDK's HTTP client. The real Stripe SDK runs, so the URLs, the paging and the error mapping are its own.
Both fakes keep state, so a second request meets what the first one left.
"""
import asyncio
import json
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import stripe

USER = "00000000-0000-0000-0000-000000000001"
CUSTOMER = "cus_123"
STRIPE_KEY = "sk_test_123"  # tests/conftest.py

# Stripe is done with a subscription in one of these: it charges nothing more.
FINISHED = ("canceled", "incomplete_expired")

# Supabase Auth for a user it does not have (supabase/auth, internal/api/errors.go): the first body goes
# to a request without X-Supabase-Api-Version, as ours; the second to one that sends the header.
USER_NOT_FOUND = {"code": 404, "error_code": "user_not_found", "msg": "User not found"}
USER_NOT_FOUND_VERSIONED = {"code": "user_not_found", "message": "User not found"}


def stripe_error(code: str | None, param: str | None, message: str, kind: str = "invalid_request_error") -> dict:
    return {"error": {"type": kind, "code": code, "param": param, "message": message}}


class FakeStripe(stripe.HTTPClient):
    """Stripe's REST API for one customer, as far as account deletion uses it.

    Three behaviours are the stricter reading of Stripe's documentation, not checked against Stripe:
    a cancel of a finished subscription answers 404; an `incomplete` subscription that an open Checkout
    page holds cannot be cancelled, only ended by expiring the page; a cancelled `incomplete`
    subscription becomes `incomplete_expired`. What the two lists answer for a customer Stripe does not
    have is not known either, so here they give a bare 400 that nothing can lean on.
    """

    name = "fake"
    PAGE = 2  # a short page, so three objects need a second request

    def __init__(self):
        super().__init__()
        self.customer: str | None = CUSTOMER  # None: Stripe has no such customer under this key
        self.customer_deleted = False  # deleted in Stripe: the id still answers, marked as deleted
        self.subscriptions: dict[str, str] = {"sub_1": "active"}
        self.checkouts: dict[str, str] = {}  # Checkout session → open | complete | expired
        self.held: dict[str, str] = {}  # open session → the subscription its failed first payment left
        self.failure: Exception | None = None  # every request raises it
        self.breaks: set[str] = set()  # ids whose cancel or expire answers 500
        self.rejects: set[str] = set()  # ids whose cancel or expire Stripe refuses with a 400: no change
        self.before: dict[str, Callable[[], None]] = {}  # what someone else does right before a write on the id
        self.asked: list[str] = []  # the customers whose subscriptions were listed
        self.requests: list[tuple[str, str]] = []
        self.on_event_loop = False

    def live(self) -> list[str]:
        return [sub_id for sub_id, state in self.subscriptions.items() if state not in FINISHED]

    # --- the SDK's HTTP client ---------------------------------------------------------------------

    def request(self, method, url, headers, post_data=None):
        try:
            asyncio.get_running_loop()
            self.on_event_loop = True
        except RuntimeError:
            pass
        parts = urlparse(url)
        method, path = method.upper(), parts.path
        self.requests.append((method, path))
        if self.failure is not None:
            raise self.failure
        if headers.get("Authorization") != f"Bearer {STRIPE_KEY}":
            status, body = 401, stripe_error(None, None, "Invalid API Key provided")
        else:
            query = {key: values[0] for key, values in parse_qs(parts.query).items()}
            status, body = self._route(method, path, query, post_data)
        return json.dumps(body), status, {"request-id": "req_fake"}

    def close(self):
        pass

    def _route(self, method: str, path: str, query: dict, post_data) -> tuple[int, dict]:
        segments = path.removeprefix("/v1/").split("/")
        if method == "GET" and segments[0] == "customers" and len(segments) == 2:
            if segments[1] != self.customer:
                return 404, stripe_error("resource_missing", "id", f"No such customer: '{segments[1]}'")
            return 200, {"id": segments[1], "object": "customer", **({"deleted": True} if self.customer_deleted else {})}
        if method == "GET" and segments == ["checkout", "sessions"]:
            return self._list(self.checkouts, "checkout.session", path, query)
        if method == "GET" and segments == ["subscriptions"]:
            self.asked.append(query.get("customer", ""))
            return self._list(self.subscriptions, "subscription", path, query)
        if method == "GET" and segments[:2] == ["checkout", "sessions"] and len(segments) == 3:
            return 200, {"id": segments[2], "object": "checkout.session", "status": self.checkouts[segments[2]]}
        if method == "GET" and segments[0] == "subscriptions" and len(segments) == 2:
            return 200, {"id": segments[1], "object": "subscription", "status": self.subscriptions[segments[1]]}
        if method == "POST" and segments[:2] == ["checkout", "sessions"] and segments[3:] == ["expire"]:
            return self._expire(segments[2], post_data)
        if method == "DELETE" and segments[0] == "subscriptions" and len(segments) == 2:
            return self._cancel(segments[1], query, post_data)
        return 404, stripe_error(None, None, f"Unrecognized request URL ({method}: {path})")

    def _list(self, objects: dict[str, str], kind: str, path: str, query: dict) -> tuple[int, dict]:
        extra = set(query) - {"customer", "status", "limit", "starting_after"}
        if extra:
            return 400, stripe_error("parameter_unknown", min(extra), "Received unknown parameter")
        if self.customer_deleted or query.get("customer") != self.customer:
            return 400, stripe_error(None, None, "Invalid request")
        wanted = query.get("status")
        # As Stripe does: no status = all that are not cancelled; "all" = every one; else that status.
        found = [
            (object_id, state)
            for object_id, state in objects.items()
            if wanted == "all" or (wanted is None and state != "canceled") or wanted == state
        ]
        ids = [object_id for object_id, _ in found]
        start = ids.index(query["starting_after"]) + 1 if "starting_after" in query else 0
        size = min(int(query.get("limit", 10)), self.PAGE)
        page = found[start : start + size]
        return 200, {
            "object": "list",
            "url": path,
            "has_more": start + size < len(found),
            "data": [{"id": object_id, "object": kind, "status": state} for object_id, state in page],
        }

    def _expire(self, session_id: str, post_data) -> tuple[int, dict]:
        if post_data:
            return 400, stripe_error("parameter_unknown", None, f"Received unknown parameters: {post_data}")
        self.before.pop(session_id, lambda: None)()
        if session_id in self.breaks:
            return 500, stripe_error(None, None, "An unknown error occurred", kind="api_error")
        if session_id in self.rejects or self.checkouts[session_id] != "open":
            return 400, stripe_error(None, None, "Only Checkout Sessions with a status in [\"open\"] can be expired.")
        self.checkouts[session_id] = "expired"
        if session_id in self.held:
            self.subscriptions[self.held[session_id]] = "incomplete_expired"
        return 200, {"id": session_id, "object": "checkout.session", "status": "expired"}

    def _cancel(self, sub_id: str, query: dict, post_data) -> tuple[int, dict]:
        if query or post_data:  # invoice_now or prorate would bill the customer on the way out
            return 400, stripe_error("parameter_unknown", None, f"Received unknown parameters: {query or post_data}")
        self.before.pop(sub_id, lambda: None)()
        if sub_id in self.breaks:
            return 500, stripe_error(None, None, "An unknown error occurred", kind="api_error")
        state = self.subscriptions[sub_id]
        if state in FINISHED:
            return 404, stripe_error("resource_missing", "id", f"No such subscription: '{sub_id}'")
        holder = next((session for session, held in self.held.items() if held == sub_id), None)
        if sub_id in self.rejects or (holder and self.checkouts[holder] == "open"):
            return 400, stripe_error(None, None, "This subscription cannot be canceled right now.")
        self.subscriptions[sub_id] = "incomplete_expired" if state == "incomplete" else "canceled"
        return 200, {"id": sub_id, "object": "subscription", "status": self.subscriptions[sub_id]}


class FakeSupabase:
    """What Supabase holds of one account. Removing the login takes its rows with it, as the cascade does."""

    def __init__(self):
        self.login = True
        self.customer: str | None = CUSTOMER
        self.recorded: list[str] = []  # the statuses in stripe_subscriptions, our copy of what Stripe told us
        self.record = "up"  # "down": answers 500; "unreachable": the connection fails
        self.files = ["avatar_1.png"]
        self.storage = "up"  # "down": answers 500; "unreachable": the connection fails
        self.revenuecat = "up"
        self.google = "up"  # "unreachable": the connection fails; "down": the deletion answers 500
        self.google_requests: list[httpx.Request] = []
        self.auth_answers: list[httpx.Response] = []  # answers that come before the real one
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        mine = self.login and request.url.params.get("user_id") == f"eq.{USER}"
        if request.url.host in ("oauth2.googleapis.com", "analyticsadmin.googleapis.com"):
            self.google_requests.append(request)
            self.calls.append(("google", f"{request.method} {request.url.host}{path}"))
            if self.google == "unreachable":
                raise httpx.ConnectError("google unreachable", request=request)
            if request.url.host == "oauth2.googleapis.com":
                return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3599, "token_type": "Bearer"})
            if self.google == "down":
                return httpx.Response(500, json={"error": {"code": 500, "message": "internal"}})
            return httpx.Response(200, json={"deletionRequestTime": "2026-11-27T12:00:00Z"})
        if "api.revenuecat.com" in str(request.url):
            self.calls.append(("revenuecat", f"{request.method} {path}"))
            if self.revenuecat == "unreachable":
                raise httpx.ConnectError("revenuecat unreachable", request=request)
            return httpx.Response(200, json={})
        if path.endswith("/rest/v1/stripe_customers"):
            has_row = mine and self.customer is not None
            return httpx.Response(200, json=[{"stripe_customer_id": self.customer}] if has_row else [])
        if path.endswith("/rest/v1/stripe_subscriptions"):
            if self.record == "unreachable":
                raise httpx.ConnectError("database unreachable", request=request)
            if self.record == "down":
                return httpx.Response(500, json={"message": "internal detail that must not reach the app"})
            return httpx.Response(200, json=[{"status": status} for status in self.recorded] if mine else [])
        if "/storage/v1/object/list/avatars" in path:
            self.calls.append(("list", request.content.decode()))
            if self.storage == "unreachable":
                raise httpx.ConnectError("storage unreachable", request=request)
            if self.storage == "down":
                return httpx.Response(500, json={"message": "down"})
            return httpx.Response(200, json=[{"name": name} for name in self.files])
        if path.endswith("/storage/v1/object/avatars") and request.method == "DELETE":
            self.calls.append(("remove", request.content.decode()))
            self.files.clear()
            return httpx.Response(200, json=[])
        if f"/auth/v1/admin/users/{USER}" in path and request.method == "DELETE":
            self.calls.append(("auth", path))
            if self.auth_answers:
                return self.auth_answers.pop(0)
            if not self.login:
                return httpx.Response(404, json=USER_NOT_FOUND)
            self.login = False
            return httpx.Response(200, json={})
        return httpx.Response(200, json=[])

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.calls]


@pytest.fixture()
def stripe_account(monkeypatch):
    """One customer with one active subscription, unless the test says otherwise."""
    fake = FakeStripe()
    monkeypatch.setattr(stripe, "default_http_client", fake)
    monkeypatch.setattr(stripe, "max_network_retries", 0)  # a failure is answered at once, with no backoff
    monkeypatch.setattr(stripe, "api_key", None)  # the key must come from this request, not from an earlier test
    return fake


@pytest.fixture()
def supabase(mock_transport):
    fake = FakeSupabase()
    mock_transport(fake)
    return fake


@pytest.fixture()
def revenuecat_key(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("REVENUECAT_SECRET_KEY", "sk_rc_test")
    get_settings.cache_clear()


GA4_PROPERTY = "123456789"
GA4_ACCOUNT_EMAIL = "ga4-deletion@flueai-test.iam.gserviceaccount.com"


@pytest.fixture()
def ga4_account(monkeypatch):
    """A service account with access to the GA4 property; returns its public key, to check the signature."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.core.config import get_settings

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    account = {
        "type": "service_account",
        "client_email": GA4_ACCOUNT_EMAIL,
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    monkeypatch.setenv("GA4_PROPERTY_ID", GA4_PROPERTY)
    monkeypatch.setenv("GA4_SERVICE_ACCOUNT_JSON", json.dumps(account))
    get_settings.cache_clear()
    return key.public_key()


def delete(client, auth_headers) -> httpx.Response:
    return client.delete("/api/users/me", headers=auth_headers)


def test_deletes_subscription_files_and_login_in_that_order(client, auth_headers, supabase, stripe_account):
    res = delete(client, auth_headers)
    assert res.status_code == 204
    assert stripe_account.asked == [CUSTOMER]
    assert stripe_account.subscriptions == {"sub_1": "canceled"}  # cancelled now, not at period end
    assert supabase.kinds() == ["list", "remove", "auth"]
    assert f"profile/user/{USER}/" in supabase.calls[0][1]
    assert f"profile/user/{USER}/avatar_1.png" in supabase.calls[1][1]


def test_without_stripe_customer_or_files_it_just_deletes_the_login(client, auth_headers, supabase, stripe_account):
    supabase.customer = None
    supabase.files = []
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.requests == []
    assert supabase.kinds() == ["list", "auth"]


@pytest.mark.parametrize(
    "failure",
    [stripe.APIConnectionError("stripe down"), RuntimeError("not a Stripe error")],
    ids=["stripe-unreachable", "any-other-error"],
)
def test_a_stripe_failure_keeps_the_account(client, auth_headers, supabase, stripe_account, revenuecat_key, failure):
    stripe_account.failure = failure
    res = delete(client, auth_headers)
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "billing_unavailable"
    assert "auth" not in supabase.kinds()
    # Nothing else was touched either: no purchase history removed, no file removed.
    assert supabase.calls == []
    assert supabase.files == ["avatar_1.png"]
    assert supabase.login is True


@pytest.mark.parametrize("storage", ["down", "unreachable"])
def test_a_leftover_avatar_does_not_keep_the_account(client, auth_headers, supabase, stripe_account, storage):
    supabase.storage = storage
    assert delete(client, auth_headers).status_code == 204
    assert supabase.kinds()[-1] == "auth"
    assert supabase.login is False


def test_an_auth_failure_is_reported(client, auth_headers, supabase, stripe_account):
    supabase.auth_answers = [httpx.Response(500, json={})]
    assert delete(client, auth_headers).status_code == 502
    assert supabase.kinds()[-1] == "auth"


def test_deleting_needs_a_session(client):
    assert client.delete("/api/users/me").status_code == 401


def test_the_purchase_history_in_revenuecat_goes_too(client, auth_headers, supabase, stripe_account, revenuecat_key):
    assert delete(client, auth_headers).status_code == 204
    assert ("revenuecat", f"DELETE /v1/subscribers/{USER}") in supabase.calls
    assert supabase.kinds()[-1] == "auth"  # the login is the last thing removed


def test_revenuecat_out_of_reach_does_not_keep_the_account(client, auth_headers, supabase, stripe_account, revenuecat_key):
    supabase.revenuecat = "unreachable"
    assert delete(client, auth_headers).status_code == 204
    assert supabase.login is False


def test_the_usage_data_in_ga4_is_asked_to_be_deleted_by_user_id(client, auth_headers, supabase, stripe_account, ga4_account):
    import jwt

    assert delete(client, auth_headers).status_code == 204
    token_request, deletion = supabase.google_requests
    assert (token_request.method, str(token_request.url)) == ("POST", "https://oauth2.googleapis.com/token")
    form = parse_qs(token_request.content.decode())
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    claims = jwt.decode(form["assertion"][0], ga4_account, algorithms=["RS256"], audience="https://oauth2.googleapis.com/token")
    assert (claims["iss"], claims["scope"]) == (GA4_ACCOUNT_EMAIL, "https://www.googleapis.com/auth/analytics.edit")
    assert (deletion.method, str(deletion.url)) == (
        "POST",
        f"https://analyticsadmin.googleapis.com/v1alpha/properties/{GA4_PROPERTY}:submitUserDeletion",
    )
    assert deletion.headers["Authorization"] == "Bearer ya29.test"
    assert json.loads(deletion.content) == {"userId": USER}
    assert supabase.kinds()[-1] == "auth"


@pytest.mark.parametrize("failure", ["unreachable", "down"])
def test_ga4_failing_does_not_keep_the_account(client, auth_headers, supabase, stripe_account, ga4_account, failure, caplog):
    supabase.google = failure
    with caplog.at_level("WARNING"):
        assert delete(client, auth_headers).status_code == 204
    assert supabase.login is False
    assert any("ga4" in record.getMessage().lower() and USER in record.getMessage() for record in caplog.records)


def test_without_ga4_configured_nothing_goes_to_google(client, auth_headers, supabase, stripe_account):
    assert delete(client, auth_headers).status_code == 204
    assert supabase.google_requests == []
    assert supabase.login is False


def test_the_stripe_calls_stay_off_the_event_loop(client, auth_headers, supabase, stripe_account):
    """The SDK blocks while it waits. On the event loop, a slow Stripe would stop every other request."""
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.requests != []
    assert stripe_account.on_event_loop is False


# --- Repeating the request -------------------------------------------------------------------------
# The 204 can be lost on the way back (mobile network, the app's 15 s limit). The app then asks again
# with a token that is still valid, for an account that is already gone or half gone.


def test_a_second_request_for_an_account_already_deleted_answers_204(client, auth_headers, supabase, stripe_account):
    assert delete(client, auth_headers).status_code == 204
    assert supabase.login is False

    again = delete(client, auth_headers)

    assert again.status_code == 204
    assert again.content == b""


@pytest.mark.parametrize("body", [USER_NOT_FOUND, USER_NOT_FOUND_VERSIONED])
def test_a_login_supabase_no_longer_has_counts_as_deleted(client, auth_headers, supabase, stripe_account, body):
    supabase.auth_answers = [httpx.Response(404, json=body)]
    assert delete(client, auth_headers).status_code == 204


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(404, json={"message": "no Route matched with those values"}),  # the API gateway
        httpx.Response(404, json={"code": 404, "error_code": "validation_failed", "msg": "user_id must be an UUID"}),
        httpx.Response(404, json={"code": 404, "msg": "User not found"}),  # the words, without the code
        httpx.Response(404, json=["user_not_found"]),
        httpx.Response(404, text="<html>Not Found</html>"),
        httpx.Response(500, json=USER_NOT_FOUND),
    ],
    ids=["gateway", "bad-user-id", "message-only", "not-an-object", "html", "500-with-the-code"],
)
def test_only_supabase_saying_user_not_found_counts_as_deleted(client, auth_headers, supabase, stripe_account, answer):
    """Guards: they pass without the change, and fail when "not found" is read too loosely."""
    supabase.auth_answers = [answer]
    assert delete(client, auth_headers).status_code == 502
    assert supabase.kinds()[-1] == "auth"


def test_after_the_login_removal_fails_a_retry_finishes_the_deletion(client, auth_headers, supabase, stripe_account):
    supabase.auth_answers = [httpx.Response(500, json={})]
    assert delete(client, auth_headers).status_code == 502
    assert stripe_account.subscriptions == {"sub_1": "canceled"}
    assert supabase.kinds()[-1] == "auth"

    assert delete(client, auth_headers).status_code == 204
    assert supabase.login is False


def test_a_cancellation_that_fails_midway_keeps_the_account_and_a_retry_finishes(
    client, auth_headers, supabase, stripe_account,
):
    stripe_account.subscriptions = {"sub_1": "active", "sub_2": "past_due"}
    stripe_account.breaks = {"sub_2"}
    res = delete(client, auth_headers)
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "billing_unavailable"
    assert supabase.calls == []
    assert supabase.login is True

    stripe_account.breaks = set()
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.subscriptions == {"sub_1": "canceled", "sub_2": "canceled"}
    assert supabase.login is False


def test_a_subscription_someone_else_just_ended_is_not_a_failure(client, auth_headers, supabase, stripe_account):
    """A second request beside this one, or the SDK's own retry, ended it between our list and our cancel."""
    stripe_account.before["sub_1"] = lambda: stripe_account.subscriptions.update(sub_1="canceled")
    assert delete(client, auth_headers).status_code == 204
    assert supabase.login is False


def test_a_cancel_that_stripe_refuses_keeps_the_account(client, auth_headers, supabase, stripe_account):
    stripe_account.rejects = {"sub_1"}
    res = delete(client, auth_headers)
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "billing_unavailable"
    assert stripe_account.subscriptions == {"sub_1": "active"}
    assert supabase.calls == []
    assert supabase.login is True


# --- What can still charge the card ----------------------------------------------------------------
# A stripe_customers row exists from the moment the checkout opens, paid or not.


def test_a_customer_who_never_subscribed_can_delete_the_account(client, auth_headers, supabase, stripe_account):
    stripe_account.subscriptions = {}
    assert delete(client, auth_headers).status_code == 204
    assert supabase.login is False


@pytest.mark.parametrize("state", ["active", "trialing", "past_due", "unpaid", "paused", "incomplete"])
def test_a_subscription_that_can_still_charge_is_ended(client, auth_headers, supabase, stripe_account, state):
    stripe_account.subscriptions = {"sub_1": state}
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.live() == []
    assert supabase.login is False


@pytest.mark.parametrize("state", FINISHED)
def test_a_finished_subscription_does_not_keep_the_account(client, auth_headers, supabase, stripe_account, state):
    stripe_account.subscriptions = {"sub_old": state}
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.subscriptions == {"sub_old": state}
    assert ("DELETE", "/v1/subscriptions/sub_old") not in stripe_account.requests  # Stripe is not asked again
    assert supabase.login is False


def test_every_live_subscription_is_cancelled_also_past_the_first_page(client, auth_headers, supabase, stripe_account):
    stripe_account.subscriptions = {"sub_old": "canceled", "sub_1": "active", "sub_2": "past_due", "sub_3": "trialing"}
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.subscriptions == {
        "sub_old": "canceled", "sub_1": "canceled", "sub_2": "canceled", "sub_3": "canceled",
    }


def test_an_open_checkout_page_is_closed(client, auth_headers, supabase, stripe_account):
    """Left open, it can be paid after the account is gone: a subscription nobody can cancel."""
    stripe_account.subscriptions = {}
    stripe_account.checkouts = {"cs_paid": "complete", "cs_1": "open", "cs_2": "open", "cs_3": "open"}
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.checkouts == {"cs_paid": "complete", "cs_1": "expired", "cs_2": "expired", "cs_3": "expired"}
    assert supabase.login is False


def test_the_subscription_a_failed_first_payment_left_ends_with_its_checkout_page(
    client, auth_headers, supabase, stripe_account,
):
    stripe_account.subscriptions = {"sub_first": "incomplete"}
    stripe_account.checkouts = {"cs_1": "open"}
    stripe_account.held = {"cs_1": "sub_first"}
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.checkouts == {"cs_1": "expired"}
    assert stripe_account.live() == []
    assert supabase.login is False


def test_a_checkout_paid_at_the_last_moment_is_cancelled_as_a_subscription(client, auth_headers, supabase, stripe_account):
    stripe_account.subscriptions = {}
    stripe_account.checkouts = {"cs_1": "open"}

    def pays():
        stripe_account.checkouts["cs_1"] = "complete"
        stripe_account.subscriptions["sub_new"] = "active"

    stripe_account.before["cs_1"] = pays
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.subscriptions == {"sub_new": "canceled"}
    assert supabase.login is False


@pytest.mark.parametrize("how", ["breaks", "rejects"])
def test_a_checkout_page_that_stays_open_keeps_the_account(client, auth_headers, supabase, stripe_account, how):
    stripe_account.checkouts = {"cs_1": "open"}
    setattr(stripe_account, how, {"cs_1"})
    res = delete(client, auth_headers)
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "billing_unavailable"
    assert stripe_account.checkouts == {"cs_1": "open"}
    assert supabase.calls == []
    assert supabase.login is True


# --- A customer Stripe does not have ---------------------------------------------------------------
# The id came from another Stripe account or mode. Stripe has nothing to cancel under it. Our own
# record of the subscriptions is the second opinion: a wrong key in the server gives the same answer.


@pytest.mark.parametrize("recorded", [[], ["canceled"], ["canceled", "incomplete_expired"]])
def test_a_customer_stripe_does_not_have_with_nothing_live_on_record_can_delete(
    client, auth_headers, supabase, stripe_account, recorded,
):
    stripe_account.customer = None
    supabase.recorded = recorded
    assert delete(client, auth_headers).status_code == 204
    assert supabase.login is False


def test_a_customer_deleted_in_stripe_with_nothing_live_on_record_can_delete(client, auth_headers, supabase, stripe_account):
    stripe_account.customer_deleted = True
    supabase.recorded = ["canceled"]
    assert delete(client, auth_headers).status_code == 204
    assert supabase.login is False


@pytest.mark.parametrize("record", ["down", "unreachable"])
def test_a_customer_stripe_does_not_have_keeps_the_account_when_the_record_cannot_be_read(
    client, auth_headers, supabase, stripe_account, record,
):
    stripe_account.customer = None
    supabase.record = record
    res = delete(client, auth_headers)
    assert res.status_code == 502
    assert res.json()["detail"] == {"code": "billing_unavailable", "message": "Não conseguimos cancelar a assinatura agora."}
    assert supabase.calls == []
    assert supabase.login is True


@pytest.mark.parametrize("recorded", [["active"], ["canceled", "past_due"], ["trialing"]])
def test_a_customer_stripe_does_not_have_with_a_live_subscription_on_record_keeps_the_account(
    client, auth_headers, supabase, stripe_account, recorded,
):
    stripe_account.customer = None
    supabase.recorded = recorded
    res = delete(client, auth_headers)
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "billing_unavailable"
    assert supabase.calls == []
    assert supabase.login is True
