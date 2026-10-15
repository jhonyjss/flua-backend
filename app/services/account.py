"""Deleting an account (DELETE /api/users/me), from the app or the web — it is one account.

Order (docs/mvp-backend-plan.md, "Excluir conta"): cancel an active Stripe subscription → remove the
user's files in Storage → delete the Supabase Auth user. Every public table with user data cascades
from auth.users/profiles (checked 2026-10-15), so the last step clears the progress too.

A Stripe failure stops the deletion: deleting the account while the card keeps being charged is the
one outcome worse than not deleting.
"""
import logging

from fastapi import HTTPException

from app.services import revenuecat, stripe_service
from app.services import supabase_admin as db

logger = logging.getLogger(__name__)

AVATAR_BUCKET = "avatars"


def avatar_prefix(user_id: str) -> str:
    """Where the web uploads the avatar (flueai app/composables/useAuth.ts)."""
    return f"profile/user/{user_id}/"


async def delete_account(user_id: str) -> None:
    customer = await db.select_one("stripe_customers", {"user_id": user_id})
    customer_id = (customer or {}).get("stripe_customer_id")
    if customer_id:
        try:
            stripe_service.cancel_subscription(customer_id, immediately=True)
        except Exception as err:
            logger.warning("account deletion stopped: stripe cancel failed for %s: %s", user_id, err)
            raise HTTPException(
                status_code=502,
                detail={"code": "billing_unavailable", "message": "Não conseguimos cancelar a assinatura agora."},
            ) from err
    try:
        # App Store / Google Play subscriptions can only be cancelled by the buyer in the store (the app
        # tells them); here the purchase history kept by RevenueCat goes away.
        await revenuecat.delete_customer(user_id)
    except Exception as err:  # noqa: BLE001 — not worth keeping the account alive
        logger.warning("revenuecat customer cleanup failed for %s: %s", user_id, err)
    try:
        await db.delete_storage_prefix(AVATAR_BUCKET, avatar_prefix(user_id))
    except HTTPException as err:
        # A leftover avatar is not worth keeping the account alive; log it and go on.
        logger.warning("avatar cleanup failed for %s: %s", user_id, err.detail)
    await db.delete_auth_user(user_id)
