"""DELETE /api/users/me: Stripe → Storage → Auth, a Stripe failure stops everything, and it can be repeated.

The two providers are faked where the process ends: Supabase at the HTTP transport, Stripe at its SDK.
Both fakes keep state, so a second request meets what the first one left.
"""
from types import SimpleNamespace

import httpx
import pytest
import stripe

USER = "00000000-0000-0000-0000-000000000001"
CUSTOMER = "cus_123"

# Stripe is done with a subscription in one of these: it charges nothing more and refuses a cancel.
FINISHED = ("canceled", "incomplete_expired")

# Supabase Auth for a user it does not have (supabase/auth, internal/api/errors.go): the first body goes
# to a request without X-Supabase-Api-Version, as ours; the second to one that sends the header.
USER_NOT_FOUND = {"code": 404, "error_code": "user_not_found", "msg": "User not found"}
USER_NOT_FOUND_VERSIONED = {"code": "user_not_found", "message": "User not found"}


class FakeStripe:
    """Stripe as the SDK shows it: the subscriptions of one customer, each with its status."""

    def __init__(self, subscriptions: dict[str, str]):
        self.subscriptions = dict(subscriptions)
        self.asked: list[str] = []  # the customers whose subscriptions were listed
        self.down = False
        self.refuses: set[str] = set()  # subscriptions whose cancellation fails

    def list(self, *, customer, status=None, limit=10, **_):
        self.asked.append(customer)
        if self.down:
            raise stripe.error.APIConnectionError("stripe down")
        # As Stripe does: no status = all that are not cancelled; "all" = every one; else that status.
        found = [
            SimpleNamespace(id=sub_id, status=state)
            for sub_id, state in self.subscriptions.items()
            if customer == CUSTOMER and (status == "all" or (status is None and state != "canceled") or status == state)
        ]
        return SimpleNamespace(data=found[:limit], auto_paging_iter=lambda: iter(found))

    def cancel(self, sub_id, **_):
        if sub_id in self.refuses:
            raise stripe.error.APIConnectionError("stripe down")
        if self.subscriptions[sub_id] in FINISHED:
            raise stripe.error.InvalidRequestError(f"No such subscription: '{sub_id}'", param="id")
        self.subscriptions[sub_id] = "canceled"
        return SimpleNamespace(id=sub_id, status="canceled")

    def modify(self, sub_id, **_):
        # "Cancel at period end" leaves the subscription as it is until the period ends.
        return SimpleNamespace(id=sub_id, status=self.subscriptions[sub_id])


class FakeSupabase:
    """What Supabase holds of one account. Removing the login takes its rows with it, as the cascade does."""

    def __init__(self, *, customer: str | None = CUSTOMER, files=("avatar_1.png",)):
        self.login = True
        self.customer = customer
        self.files = list(files)
        self.storage_down = False
        self.auth_answers: list[httpx.Response] = []  # answers that come before the real one
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "api.revenuecat.com" in str(request.url):
            self.calls.append(("revenuecat", f"{request.method} {path}"))
            return httpx.Response(200, json={})
        if path.endswith("/stripe_customers"):
            has_row = self.login and self.customer is not None
            return httpx.Response(200, json=[{"stripe_customer_id": self.customer}] if has_row else [])
        if "/storage/v1/object/list/avatars" in path:
            self.calls.append(("list", request.content.decode()))
            if self.storage_down:
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
    fake = FakeStripe({"sub_1": "active"})
    monkeypatch.setattr(stripe.Subscription, "list", fake.list)
    monkeypatch.setattr(stripe.Subscription, "cancel", fake.cancel)  # the SDK has two names for
    monkeypatch.setattr(stripe.Subscription, "delete", fake.cancel)  # DELETE /v1/subscriptions/:id
    monkeypatch.setattr(stripe.Subscription, "modify", fake.modify)
    return fake


@pytest.fixture()
def supabase(mock_transport):
    fake = FakeSupabase()
    mock_transport(fake)
    return fake


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
    assert stripe_account.asked == []
    assert supabase.kinds() == ["list", "auth"]


def test_a_stripe_failure_keeps_the_account(client, auth_headers, supabase, stripe_account):
    stripe_account.down = True
    res = delete(client, auth_headers)
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "billing_unavailable"
    assert "auth" not in supabase.kinds()
    assert supabase.login is True


def test_a_leftover_avatar_does_not_keep_the_account(client, auth_headers, supabase, stripe_account):
    supabase.storage_down = True
    assert delete(client, auth_headers).status_code == 204
    assert supabase.kinds()[-1] == "auth"


def test_an_auth_failure_is_reported(client, auth_headers, supabase, stripe_account):
    supabase.auth_answers = [httpx.Response(500, json={})]
    assert delete(client, auth_headers).status_code == 502


def test_deleting_needs_a_session(client):
    assert client.delete("/api/users/me").status_code == 401


def test_the_purchase_history_in_revenuecat_goes_too(client, auth_headers, supabase, stripe_account, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("REVENUECAT_SECRET_KEY", "sk_rc_test")
    get_settings.cache_clear()
    assert delete(client, auth_headers).status_code == 204
    assert ("revenuecat", f"DELETE /v1/subscribers/{USER}") in supabase.calls
    assert supabase.kinds()[-1] == "auth"  # the login is the last thing removed


# --- Repeating the request -------------------------------------------------------------------------
# The 204 can be lost on the way back (mobile network, the app's 15 s limit). The app then asks again
# with a token that is still valid, for an account that is already gone.


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
        httpx.Response(404, json=["user_not_found"]),
        httpx.Response(404, text="<html>Not Found</html>"),
        httpx.Response(500, json=USER_NOT_FOUND),
    ],
    ids=["gateway", "bad-user-id", "not-an-object", "html", "500-with-the-code"],
)
def test_only_supabase_saying_user_not_found_counts_as_deleted(client, auth_headers, supabase, stripe_account, answer):
    supabase.auth_answers = [answer]
    assert delete(client, auth_headers).status_code == 502
    assert supabase.login is True


def test_after_the_login_removal_fails_a_retry_finishes_the_deletion(client, auth_headers, supabase, stripe_account):
    supabase.auth_answers = [httpx.Response(500, json={})]
    assert delete(client, auth_headers).status_code == 502
    assert stripe_account.subscriptions == {"sub_1": "canceled"}
    assert supabase.login is True

    assert delete(client, auth_headers).status_code == 204
    assert supabase.login is False


def test_a_cancellation_that_fails_midway_keeps_the_account_and_a_retry_finishes(
    client, auth_headers, supabase, stripe_account,
):
    stripe_account.subscriptions = {"sub_1": "active", "sub_2": "past_due"}
    stripe_account.refuses = {"sub_2"}
    res = delete(client, auth_headers)
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "billing_unavailable"
    assert supabase.login is True

    stripe_account.refuses = set()
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.subscriptions == {"sub_1": "canceled", "sub_2": "canceled"}
    assert supabase.login is False


# --- Subscriptions that are not "active" -----------------------------------------------------------
# A stripe_customers row exists from the moment the checkout opens, paid or not.


def test_a_customer_who_never_subscribed_can_delete_the_account(client, auth_headers, supabase, stripe_account):
    stripe_account.subscriptions = {}
    assert delete(client, auth_headers).status_code == 204
    assert supabase.login is False


@pytest.mark.parametrize("state", ["active", "trialing", "past_due", "unpaid", "paused", "incomplete"])
def test_a_subscription_that_can_still_charge_is_cancelled(client, auth_headers, supabase, stripe_account, state):
    stripe_account.subscriptions = {"sub_1": state}
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.subscriptions == {"sub_1": "canceled"}
    assert supabase.login is False


@pytest.mark.parametrize("state", FINISHED)
def test_a_finished_subscription_does_not_keep_the_account(client, auth_headers, supabase, stripe_account, state):
    stripe_account.subscriptions = {"sub_old": state}
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.subscriptions == {"sub_old": state}
    assert supabase.login is False


def test_every_live_subscription_of_the_customer_is_cancelled(client, auth_headers, supabase, stripe_account):
    stripe_account.subscriptions = {"sub_old": "canceled", "sub_1": "active", "sub_2": "past_due"}
    assert delete(client, auth_headers).status_code == 204
    assert stripe_account.subscriptions == {"sub_old": "canceled", "sub_1": "canceled", "sub_2": "canceled"}
