"""Minimal Supabase REST client using the service-role key (bypasses RLS).

Used for server-side table access (stripe_customers, subscriptions) — parity
with `serverSupabaseServiceRole` in the Nuxt server.
"""
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client


def _headers(settings, *, upsert: bool = False) -> dict:
    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    if upsert:
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    return headers


def _require_config(settings) -> None:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise HTTPException(500, "Supabase service credentials not configured")


async def select_one(table: str, filters: dict[str, str]) -> dict | None:
    """SELECT * FROM table WHERE ... LIMIT 1."""
    settings = get_settings()
    _require_config(settings)
    params = {f"{k}": f"eq.{v}" for k, v in filters.items()}
    params["limit"] = "1"
    async with http_client(timeout=15.0) as client:
        res = await client.get(
            f"{settings.supabase_url}/rest/v1/{table}",
            params=params,
            headers=_headers(settings),
        )
    if res.status_code != 200:
        raise HTTPException(502, f"Supabase error {res.status_code}: {res.text[:200]}")
    rows = res.json()
    return rows[0] if rows else None


async def upsert(table: str, row: dict, on_conflict: str) -> None:
    settings = get_settings()
    _require_config(settings)
    async with http_client(timeout=15.0) as client:
        res = await client.post(
            f"{settings.supabase_url}/rest/v1/{table}?on_conflict={on_conflict}",
            json=row,
            headers=_headers(settings, upsert=True),
        )
    if res.status_code not in (200, 201):
        raise HTTPException(502, f"Supabase upsert error {res.status_code}: {res.text[:200]}")
