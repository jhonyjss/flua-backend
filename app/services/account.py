"""Deleting an account (DELETE /api/users/me), from the app or the web — it is one account.

Order (docs/mvp-backend-plan.md, "Excluir conta"): cancel an active Stripe subscription → remove the
RevenueCat customer and ask GA4 to delete the User-ID (both best effort) → remove the user's files in
Storage → delete the Supabase Auth user. Every public table with user data cascades
from auth.users/profiles (checked 2026-10-15), so the last step clears the progress too.

A Stripe failure stops the deletion: deleting the account while the card keeps being charged is the
one outcome worse than not deleting. So every subscription that can still charge is cancelled, not
only an `active` one, and an open Checkout page is closed.

The request can be repeated. The 204 may be lost on its way to the app, or a step may fail after
Stripe was cancelled; the next request then meets steps already done. Nothing left to cancel and a
login Supabase no longer has both count as done.
"""
import asyncio
import logging

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from app.services import ga4, revenuecat, stripe_service
from app.services import supabase_admin as db

logger = logging.getLogger(__name__)

AVATAR_BUCKET = "avatars"
# The whole GA4 step (token + deletion): a stuck Google must not hold the 204 for long.
GA4_DELETION_BUDGET_S = 10.0


def avatar_prefix(user_id: str) -> str:
    """Where the web uploads the avatar (flueai app/composables/useAuth.ts)."""
    return f"profile/user/{user_id}/"


async def delete_account(user_id: str) -> None:
    customer = await db.select_one("stripe_customers", {"user_id": user_id})
    customer_id = (customer or {}).get("stripe_customer_id")
    if customer_id:
        await _stop_stripe_billing(user_id, customer_id)
    try:
        # App Store / Google Play subscriptions can only be cancelled by the buyer in the store (the app
        # tells them); here the purchase history kept by RevenueCat goes away.
        await revenuecat.delete_customer(user_id)
    except Exception as err:  # noqa: BLE001 — not worth keeping the account alive
        logger.warning("revenuecat customer cleanup failed for %s: %s", user_id, err)
    try:
        # The app sends GA4 the account id as User-ID; its events go with the account.
        await asyncio.wait_for(ga4.delete_user(user_id), GA4_DELETION_BUDGET_S)
    except Exception as err:  # noqa: BLE001 — Google out of reach is not worth keeping the account alive
        # Error, with a fixed marker: the privacy texts promise this deletion, so the owner resends it by hand.
        logger.error("ga4_deletion_failed user=%s: %s", user_id, type(err).__name__ if isinstance(err, TimeoutError) else err)
    try:
        await db.delete_storage_prefix(AVATAR_BUCKET, avatar_prefix(user_id))
    except Exception as err:  # noqa: BLE001 — a leftover avatar is not worth keeping the account alive
        logger.warning("avatar cleanup failed for %s: %s", user_id, getattr(err, "detail", err))
    await db.delete_auth_user(user_id)


def _billing_unavailable() -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={"code": "billing_unavailable", "message": "Não conseguimos cancelar a assinatura agora."},
    )


async def _stop_stripe_billing(user_id: str, customer_id: str) -> None:
    try:
        # The Stripe SDK blocks while it waits. In a worker thread, a slow Stripe does not stop the
        # event loop, and with it every other request.
        cancelled = await run_in_threadpool(stripe_service.stop_billing, customer_id)
    except stripe_service.UnknownCustomer:
        await _confirm_nothing_live_on_record(user_id, customer_id)
    except Exception as err:
        logger.warning("account deletion stopped: stripe cancel failed for %s: %s", user_id, err)
        raise _billing_unavailable() from err
    else:
        logger.info("account deletion: cancelled %d stripe subscription(s) for %s", cancelled, user_id)


async def _confirm_nothing_live_on_record(user_id: str, customer_id: str) -> None:
    """Stripe has no such customer: the id came from another Stripe account or mode, or was deleted there.

    Nothing to cancel under it, then. A wrong key in this server gives the same answer, so our own
    record of the subscriptions must agree; if it shows a live one, or cannot be read, the account stays.
    """
    try:
        rows = await db.select_many("stripe_subscriptions", {"user_id": user_id}, select="status")
    except Exception as err:
        logger.warning("account deletion stopped: no subscription record could be read for %s: %s", user_id, err)
        raise _billing_unavailable() from err
    if any(row.get("status") not in stripe_service.FINISHED for row in rows):
        logger.error(
            "account deletion stopped: stripe has no customer %s, and %s has a live subscription on record",
            customer_id, user_id,
        )
        raise _billing_unavailable()
    logger.warning("stripe has no customer %s for %s; nothing to cancel", customer_id, user_id)
