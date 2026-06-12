"""Thin Anthropic Messages API client (REST via httpx — easy to mock in tests)."""
import json
import re

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


async def complete(
    system: str,
    user_message: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.3,
    model: str | None = None,
    messages: list[dict] | None = None,
) -> str:
    """Run one completion and return the text content."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured")

    payload = {
        "model": model or settings.anthropic_model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": messages or [{"role": "user", "content": user_message}],
    }
    async with http_client(timeout=60.0) as client:
        res = await client.post(
            API_URL,
            json=payload,
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
        )
    if res.status_code != 200:
        raise HTTPException(502, f"Anthropic error {res.status_code}: {res.text[:200]}")

    data = res.json()
    parts = data.get("content") or []
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")


def extract_json(text: str) -> dict:
    """Tolerant JSON extraction: handles ```json fences and surrounding prose."""
    candidate = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end > start:
            candidate = candidate[start: end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as err:
        raise ValueError(f"Model did not return valid JSON: {text[:200]}") from err
    if not isinstance(parsed, dict):
        raise ValueError("Model returned JSON that is not an object")
    return parsed
