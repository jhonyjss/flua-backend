"""STT — Deepgram + Whisper; JSON base64 and multipart (parity with transcribe.post.ts)."""
from __future__ import annotations

import base64
import os

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client
from app.schemas.ai import TranscribeJsonRequest, TranscribeResult, TranscribeWord
from app.services.openai_client import transcribe_whisper


async def transcribe_deepgram_pcm(
    audio: bytes,
    *,
    sample_rate: int = 16000,
    language: str = "en",
) -> TranscribeResult:
    settings = get_settings()
    if not settings.deepgram_api_key:
        raise HTTPException(500, "DEEPGRAM_API_KEY not configured")

    is_multi = language == "multi"
    dg_lang = "multi" if is_multi else (language.split("-")[0] or "en")
    params = (
        f"model=nova-2&language={dg_lang}&smart_format=true&punctuate=true"
        f"&encoding=linear16&sample_rate={sample_rate}&channels=1"
    )
    if is_multi:
        params += "&detect_language=true"

    async with http_client(timeout=60.0) as client:
        res = await client.post(
            f"https://api.deepgram.com/v1/listen?{params}",
            content=audio,
            headers={
                "Authorization": f"Token {settings.deepgram_api_key}",
                "Content-Type": "application/octet-stream",
            },
        )
    if res.status_code != 200:
        raise HTTPException(502, f"Deepgram error {res.status_code}: {res.text[:200]}")

    data = res.json()
    try:
        alt = data["results"]["channels"][0]["alternatives"][0]
        words = [
            TranscribeWord(word=w.get("word", ""), start=w.get("start", 0), end=w.get("end", 0), confidence=w.get("confidence", 0))
            for w in alt.get("words") or []
        ]
        return TranscribeResult(
            success=True,
            transcript=alt.get("transcript", ""),
            confidence=alt.get("confidence"),
            words=words,
            provider="deepgram",
        )
    except (KeyError, IndexError):
        return TranscribeResult(success=True, transcript="", provider="deepgram")


async def transcribe_file(audio: bytes, content_type: str, language: str = "en") -> TranscribeResult:
    settings = get_settings()
    if not settings.deepgram_api_key:
        raise HTTPException(500, "DEEPGRAM_API_KEY not configured")
    params = f"model=nova-2&language={language.split('-')[0]}&smart_format=true"
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
        return TranscribeResult(
            success=True,
            transcript=alt.get("transcript", ""),
            confidence=alt.get("confidence"),
            provider="deepgram",
        )
    except (KeyError, IndexError):
        return TranscribeResult(success=True, transcript="", provider="deepgram")


def _resolve_provider(requested: str | None) -> str:
    settings = get_settings()
    if requested in ("deepgram", "whisper"):
        return requested
    env = os.environ.get("STT_PROVIDER", "").lower()
    if env in ("deepgram", "whisper"):
        return env
    if settings.deepgram_api_key:
        return "deepgram"
    if settings.openai_api_key:
        return "whisper"
    return "deepgram"


async def transcribe_json(body: TranscribeJsonRequest) -> TranscribeResult:
    try:
        audio = base64.b64decode(body.audio, validate=False)
    except Exception as exc:
        return TranscribeResult(success=False, error=f"Invalid audio base64: {exc}")

    provider = _resolve_provider(body.provider)
    language = body.language or "en"

    if provider == "whisper":
        if not get_settings().openai_api_key:
            return TranscribeResult(success=False, error="OPENAI_API_KEY not configured for Whisper")
        text, _ = await transcribe_whisper(audio, sample_rate=body.sampleRate, language=language)
        return TranscribeResult(success=True, transcript=text, provider="whisper")

    return await transcribe_deepgram_pcm(audio, sample_rate=body.sampleRate, language=language)
