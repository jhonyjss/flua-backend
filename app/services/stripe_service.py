"""Stripe billing (parity with server/api/stripe in the Nuxt repo).

The official `stripe` SDK is synchronous; FastAPI runs these handlers in the
threadpool (routes are `def`, not `async def`).
"""
import logging

import stripe
from fastapi import HTTPException

from app.core.config import get_settings

logger = logging.getLogger("flueai.stripe")


def _client() -> None:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(500, "STRIPE_SECRET_KEY not configured")
    stripe.api_key = settings.stripe_secret_key


def create_customer(email: str | None, user_id: str) -> str:
    _client()
    customer = stripe.Customer.create(email=email, metadata={"supabase_user_id": user_id})
    return customer.id


def customer_exists(customer_id: str) -> bool:
    _client()
    try:
        customer = stripe.Customer.retrieve(customer_id)
        return not getattr(customer, "deleted", False)
    except stripe.error.InvalidRequestError:
        return False


def create_checkout_session(
    *, customer_id: str, price_id: str, user_id: str,
    success_url: str, cancel_url: str,
) -> tuple[str, str]:
    """Returns (url, session_id)."""
    _client()
    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        allow_promotion_codes=True,
        subscription_data={"metadata": {"supabase_user_id": user_id}},
        metadata={"supabase_user_id": user_id},
    )
    if not session.url:
        raise HTTPException(502, "Stripe não retornou URL de checkout")
    return session.url, session.id


def create_portal_session(customer_id: str, return_url: str) -> str:
    _client()
    session = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
    return session.url


def cancel_subscription(customer_id: str, *, immediately: bool = False) -> bool:
    """Cancel the customer's active subscription (at period end by default)."""
    _client()
    subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
    if not subs.data:
        raise HTTPException(404, "Nenhuma assinatura ativa encontrada")
    sub = subs.data[0]
    if immediately:
        stripe.Subscription.delete(sub.id)
        return False
    stripe.Subscription.modify(sub.id, cancel_at_period_end=True)
    return True


# Stripe is done with a subscription in one of these: nothing more is charged.
FINISHED = frozenset({"canceled", "incomplete_expired"})


class UnknownCustomer(Exception):
    """Stripe has no customer with this id under the key in use."""


def stop_billing(customer_id: str) -> int:
    """Leaves the customer with nothing that can charge the card; returns how many subscriptions it cancelled.

    For account deletion. It may run again after a failure, or beside a second request, so every
    step accepts that someone already did it. `cancel_subscription` is the "cancel my plan" button:
    it looks only at `active` and answers 404 when there is none.

    Raises UnknownCustomer when Stripe has no such customer.
    """
    _client()
    try:
        # An open Checkout page can still be paid after the account is gone. Closing it also ends the
        # `incomplete` subscription that a failed first payment left behind.
        open_pages = list(
            stripe.checkout.Session.list(customer=customer_id, status="open", limit=100).auto_paging_iter()
        )
        for page in open_pages:
            _expire_checkout(page.id)
        # Listed after the pages are closed: one paid at the last moment is a subscription by now.
        subscriptions = list(
            stripe.Subscription.list(customer=customer_id, status="all", limit=100).auto_paging_iter()
        )
    except stripe.InvalidRequestError as err:
        if err.code == "resource_missing" and err.param == "customer":
            raise UnknownCustomer(customer_id) from err
        raise
    return sum(_cancel_now(sub.id) for sub in subscriptions if sub.status not in FINISHED)


def _expire_checkout(session_id: str) -> None:
    try:
        stripe.checkout.Session.expire(session_id)
    except stripe.InvalidRequestError:
        # Refused. Fine when the page closed since the list: paid, or expired by another request.
        if stripe.checkout.Session.retrieve(session_id).status == "open":
            raise


def _cancel_now(subscription_id: str) -> bool:
    """False when it was already finished: a request beside this one, or the SDK's own retry, got there first."""
    try:
        stripe.Subscription.cancel(subscription_id)
    except stripe.InvalidRequestError:
        if stripe.Subscription.retrieve(subscription_id).status not in FINISHED:
            raise
        return False
    return True


def list_invoices(customer_id: str, limit: int = 12) -> list[dict]:
    _client()
    invoices = stripe.Invoice.list(customer=customer_id, limit=limit)
    return [
        {
            "id": inv.id,
            "amount_paid": inv.amount_paid,
            "currency": inv.currency,
            "status": inv.status or "open",
            "hosted_invoice_url": inv.hosted_invoice_url,
            "created_at": _ts_to_iso(inv.created),
        }
        for inv in invoices.data
    ]


def verify_webhook(payload: bytes, signature: str) -> stripe.Event:
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(500, "STRIPE_WEBHOOK_SECRET not configured")
    try:
        return stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except (stripe.error.SignatureVerificationError, ValueError) as err:
        raise HTTPException(400, "Invalid webhook signature") from err


def _ts_to_iso(ts: int | None) -> str:
    from datetime import datetime, timezone
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
