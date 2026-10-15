"""In-app purchases through RevenueCat (App Store and Google Play).

The app identifies the buyer to RevenueCat with the Supabase user id (Purchases.logIn), so RevenueCat's
app_user_id is our user id. Whenever something changes — a webhook, or the app right after a purchase —
we read the customer's current state from RevenueCat's API (GET /v1/subscribers, the handling RevenueCat
recommends over interpreting each event) and keep it in app_store_subscriptions, one row per account.
get_subscription (user_data) joins that row with Stripe, so a plan bought in the app counts on the site
and vice versa.

Entitlements configured in RevenueCat: "starter" and "pro" (the site's plans). Product ids carry the
period, e.g. flueai_pro_monthly / flueai_pro_yearly.
"""
import re
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client
from app.schemas.users import SubscriptionInfo
from app.services import supabase_admin as db

API = "https://api.revenuecat.com/v1"
TABLE = "app_store_subscriptions"
PLAN_RANK = {"starter": 1, "pro": 2, "premium": 3}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def is_account_id(app_user_id: str | None) -> bool:
    """Our users are Supabase UUIDs; RevenueCat's anonymous ids ($RCAnonymousID:…) are not ours."""
    return bool(app_user_id and _UUID.match(app_user_id))


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _live_until(entitlement: dict) -> datetime | None | bool:
    """When access ends: a date, None for lifetime, or False when it already ended."""
    expires = _parse(entitlement.get("expires_date"))
    grace = _parse(entitlement.get("grace_period_expires_date"))
    if entitlement.get("expires_date") is None:
        return None
    end = max(d for d in (expires, grace) if d) if (expires or grace) else None
    return end if end and end > datetime.now(UTC) else False


def state_from_subscriber(subscriber: dict) -> dict:
    """The row to keep for this customer: the best active entitlement, or none."""
    best: tuple[int, str, dict, datetime | None] | None = None
    for name, entitlement in (subscriber.get("entitlements") or {}).items():
        until = _live_until(entitlement)
        if until is False:
            continue
        rank = PLAN_RANK.get(name, 0)
        if best is None or rank > best[0]:
            best = (rank, name, entitlement, until)
    if best is None:
        return {"entitlement": None, "product_id": None, "store": None, "period_type": None,
                "expires_at": None, "will_renew": False, "billing_issue": False}
    _, name, entitlement, until = best
    product = entitlement.get("product_identifier")
    sub = (subscriber.get("subscriptions") or {}).get(product) or {}
    return {
        "entitlement": name,
        "product_id": product,
        "store": sub.get("store"),
        "period_type": sub.get("period_type"),
        "expires_at": until.isoformat() if until else None,
        "will_renew": not sub.get("unsubscribe_detected_at"),
        "billing_issue": bool(sub.get("billing_issues_detected_at")),
    }


def subscription_info(row: dict | None) -> SubscriptionInfo:
    """The row as SubscriptionInfo, the shape the site and the app already read."""
    if not row or not row.get("entitlement"):
        return SubscriptionInfo()
    expires = _parse(row.get("expires_at"))
    active = expires is None or expires > datetime.now(UTC)
    if not active:
        return SubscriptionInfo(source=row.get("store"))
    product = (row.get("product_id") or "").lower()
    period = "yearly" if ("year" in product or "annual" in product) else "monthly"
    status = "past_due" if row.get("billing_issue") else "trialing" if row.get("period_type") == "trial" else "active"
    return SubscriptionInfo(
        isSubscribed=True,
        planLevel=f"{row['entitlement']}_{period}",
        planName=row.get("product_id"),
        status=status,
        cancelAtPeriodEnd=not row.get("will_renew", True),
        currentPeriodEnd=row.get("expires_at"),
        source=row.get("store"),
    )


async def fetch_subscriber(user_id: str) -> dict:
    settings = get_settings()
    if not settings.revenuecat_secret_key:
        raise HTTPException(503, "RevenueCat is not configured")
    async with http_client(timeout=15.0) as client:
        res = await client.get(
            f"{API}/subscribers/{quote(user_id, safe='')}",
            headers={"Authorization": f"Bearer {settings.revenuecat_secret_key}"},
        )
    if res.status_code != 200:
        raise HTTPException(502, f"RevenueCat error {res.status_code}")
    return res.json().get("subscriber") or {}


async def sync(user_id: str, event_id: str | None = None) -> SubscriptionInfo:
    """Reads the customer's state from RevenueCat and keeps it; idempotent."""
    state = state_from_subscriber(await fetch_subscriber(user_id))
    row = {"user_id": user_id, **state, "last_event_id": event_id, "updated_at": datetime.now(UTC).isoformat()}
    await db.upsert(TABLE, row, on_conflict="user_id")
    return subscription_info(row)


async def stored(user_id: str) -> SubscriptionInfo:
    return subscription_info(await db.select_one(TABLE, {"user_id": user_id}))


async def delete_customer(user_id: str) -> None:
    """Removes the customer from RevenueCat when the account is deleted (their purchase history)."""
    settings = get_settings()
    if not settings.revenuecat_secret_key:
        return
    async with http_client(timeout=15.0) as client:
        await client.delete(
            f"{API}/subscribers/{quote(user_id, safe='')}",
            headers={"Authorization": f"Bearer {settings.revenuecat_secret_key}"},
        )


def event_user_ids(event: dict) -> list[str]:
    """Which of our accounts an event is about: the receiver of a transfer, else the buyer."""
    if event.get("type") == "TEST":
        return []
    ids = event.get("transferred_to") if event.get("type") == "TRANSFER" else [event.get("app_user_id")]
    return [i for i in (ids or []) if is_account_id(i)]
