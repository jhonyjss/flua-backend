"""Stripe billing endpoints — parity with server/api/stripe in the Nuxt repo.

Routes are sync (`def`) so the synchronous Stripe SDK runs in the threadpool.
Customer mapping lives in the Supabase `stripe_customers` table.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import AuthUser, get_current_user
from app.core.config import get_settings
from app.schemas.billing import (
    CancelRequest,
    CancelResponse,
    CheckoutRequest,
    CheckoutResponse,
    InvoicesResponse,
    PortalResponse,
)
from app.services import stripe_service, supabase_admin

logger = logging.getLogger("flueai.billing")
router = APIRouter(prefix="/api/stripe", tags=["billing"])


async def _get_or_create_customer(user: AuthUser) -> str:
    """Get the user's Stripe customer id, verifying it still exists (parity
    with the Nuxt checkout handler), creating + persisting when needed."""
    row = await supabase_admin.select_one("stripe_customers", {"user_id": user.id})
    customer_id = (row or {}).get("stripe_customer_id")
    if customer_id and stripe_service.customer_exists(customer_id):
        return customer_id
    customer_id = stripe_service.create_customer(user.email, user.id)
    await supabase_admin.upsert(
        "stripe_customers",
        {"user_id": user.id, "stripe_customer_id": customer_id, "email": user.email},
        on_conflict="user_id",
    )
    return customer_id


@router.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(
    body: CheckoutRequest, user: AuthUser = Depends(get_current_user),
) -> CheckoutResponse:
    settings = get_settings()
    price_id = settings.stripe_price_id(body.planName, body.billing)
    if not price_id:
        raise HTTPException(
            500,
            f"Price ID não configurado para {body.planName}/{body.billing}. "
            f"Defina STRIPE_PRICE_{body.planName.upper()}_{body.billing.upper()}.",
        )
    customer_id = await _get_or_create_customer(user)
    url, session_id = stripe_service.create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        user_id=user.id,
        success_url=body.successUrl or f"{settings.frontend_url}/subscription-success",
        cancel_url=body.cancelUrl or f"{settings.frontend_url}/pricing?canceled=1",
    )
    return CheckoutResponse(url=url, sessionId=session_id)


@router.post("/create-portal-session", response_model=PortalResponse)
async def create_portal_session(user: AuthUser = Depends(get_current_user)) -> PortalResponse:
    settings = get_settings()
    row = await supabase_admin.select_one("stripe_customers", {"user_id": user.id})
    customer_id = (row or {}).get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(404, "Cliente Stripe não encontrado")
    url = stripe_service.create_portal_session(customer_id, f"{settings.frontend_url}/settings/billing")
    return PortalResponse(url=url)


@router.post("/cancel-subscription", response_model=CancelResponse)
async def cancel_subscription(
    body: CancelRequest, user: AuthUser = Depends(get_current_user),
) -> CancelResponse:
    row = await supabase_admin.select_one("stripe_customers", {"user_id": user.id})
    customer_id = (row or {}).get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(404, "Cliente Stripe não encontrado")
    cancel_at_period_end = stripe_service.cancel_subscription(customer_id, immediately=body.immediately)
    return CancelResponse(success=True, cancelAtPeriodEnd=cancel_at_period_end)


@router.get("/get-invoices", response_model=InvoicesResponse)
async def get_invoices(user: AuthUser = Depends(get_current_user)) -> InvoicesResponse:
    row = await supabase_admin.select_one("stripe_customers", {"user_id": user.id})
    customer_id = (row or {}).get("stripe_customer_id")
    if not customer_id:
        return InvoicesResponse(invoices=[])
    return InvoicesResponse(invoices=stripe_service.list_invoices(customer_id))


@router.post("/webhook")
async def webhook(request: Request) -> dict:
    """Stripe webhook: verifies signature and dispatches subscription events.

    TODO(parity): port the full Supabase table sync from the Nuxt
    server/api/stripe/webhook.post.ts (subscriptions upsert per event type).
    Until the cutover, keep the Nuxt webhook as the registered endpoint in the
    Stripe dashboard and treat this one as shadow/staging.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    event = stripe_service.verify_webhook(payload, signature)

    handled = {
        "checkout.session.completed",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
    }
    if event["type"] in handled:
        logger.info("stripe webhook received: %s (%s)", event["type"], event["id"])
    return {"received": True}
