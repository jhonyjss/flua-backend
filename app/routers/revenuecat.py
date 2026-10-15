"""RevenueCat webhook and the app's post-purchase sync (app/services/revenuecat.py)."""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.core.auth import AuthUser
from app.core.config import get_settings
from app.core.rate_limit import rate_limited
from app.schemas.users import SubscriptionInfo
from app.services import revenuecat

router = APIRouter(prefix="/api/revenuecat", tags=["billing"])


@router.post("/webhook")
async def webhook(request: Request, authorization: str = Header(default="")) -> dict:
    expected = get_settings().revenuecat_webhook_auth
    if not expected:
        raise HTTPException(503, "RevenueCat webhook is not configured")
    if not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(401, "Invalid webhook authorization")
    event = (await request.json()).get("event") or {}
    # A failure reading RevenueCat raises 502, and RevenueCat retries the delivery later.
    for user_id in revenuecat.event_user_ids(event):
        await revenuecat.sync(user_id, event_id=event.get("id"))
    return {"ok": True}


@router.post("/sync", response_model=SubscriptionInfo)
async def sync_after_purchase(
    user: AuthUser = Depends(rate_limited("revenuecat_sync", max_requests=10, window_seconds=60)),
) -> SubscriptionInfo:
    """Called by the app right after a purchase or a restore, so the plan unlocks without waiting for
    the webhook (which can take up to a minute)."""
    return await revenuecat.sync(user.id)
