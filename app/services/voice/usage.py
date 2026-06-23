"""Voice usage tracking via Supabase REST."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client


def _month_start_iso() -> str:
    now = datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc).isoformat()


async def get_used_minutes(user_id: str) -> float:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        return 0.0
    async with http_client(timeout=15.0) as client:
        res = await client.get(
            f"{settings.supabase_url}/rest/v1/voice_usage",
            params={
                "user_id": f"eq.{user_id}",
                "created_at": f"gte.{_month_start_iso()}",
                "select": "minutes",
            },
            headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
            },
        )
    if res.status_code != 200:
        raise HTTPException(500, "Failed to fetch voice usage")
    rows = res.json()
    return float(sum((r.get("minutes") or 0) for r in rows))


async def record_minutes(user_id: str, minutes: float, engine: str) -> float:
    settings = get_settings()
    minutes = max(0.0, min(minutes, 120.0))
    if minutes <= 0:
        return 0.0
    if not settings.supabase_url or not settings.supabase_service_key:
        return minutes
    async with http_client(timeout=15.0) as client:
        res = await client.post(
            f"{settings.supabase_url}/rest/v1/voice_usage",
            json={"user_id": user_id, "minutes": minutes, "engine": engine},
            headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
    if res.status_code not in (200, 201, 204):
        raise HTTPException(500, "Failed to record voice usage")
    return minutes
