"""STT via Deepgram (parity with server/api/ai/transcribe.post.ts)."""
from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client


async def transcribe(audio: bytes, content_type: str, language: str = "en") -> tuple[str, float | None]:
    """Transcribe audio bytes; returns (transcript, confidence)."""
    settings = get_settings()
    if not settings.deepgram_api_key:
        raise HTTPException(500, "DEEPGRAM_API_KEY not configured")

    params = f"model=nova-2&language={language}&smart_format=true"
    async with http_client(timeout=60.0) as client:
        res = await client.post(
            f"https://api.deepgram.com/v1/listen?{params}",
            content=audio,
            headers={
                "Authorization": f"Token {settings.deepgram_api_key}",
                "Content-Type": content_type or "audio/webm",
            },
        )
    if res.status_code != 200:
        raise HTTPException(502, f"Deepgram error {res.status_code}: {res.text[:200]}")

    data = res.json()
    try:
        alt = data["results"]["channels"][0]["alternatives"][0]
        return alt.get("transcript", ""), alt.get("confidence")
    except (KeyError, IndexError):
        return "", None
