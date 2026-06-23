"""Avatar model proxy — port of server/api/avatar/model.get.ts."""
from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import Response

from app.core.http import http_client

ALLOWED_DOMAINS = (
    "models.readyplayer.me",
    "api.readyplayer.me",
    "d1a370nemizbjq.cloudfront.net",
)

_cache: dict[str, bytes] = {}


def _is_allowed(hostname: str) -> bool:
    return any(hostname == d or hostname.endswith(f".{d}") for d in ALLOWED_DOMAINS)


async def fetch_model(model_url: str) -> Response:
    if not model_url:
        raise HTTPException(400, "Missing url parameter")
    try:
        from urllib.parse import urlparse

        parsed = urlparse(model_url)
    except Exception:
        raise HTTPException(400, "Invalid URL") from None

    if not _is_allowed(parsed.hostname or ""):
        raise HTTPException(403, "Domain not allowed")

    if model_url in _cache:
        data = _cache[model_url]
    else:
        async with http_client(timeout=120.0) as client:
            res = await client.get(model_url)
        if res.status_code != 200:
            raise HTTPException(res.status_code, f"Failed to fetch model: {res.status_code}")
        data = res.content
        _cache[model_url] = data

    return Response(
        content=data,
        media_type="model/gltf-binary",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )
