"""OpenAI REST client — Responses API, Whisper STT, TTS."""
from __future__ import annotations

import base64
import struct
from typing import Any

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client


def _auth_headers() -> dict[str, str]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(500, "OPENAI_API_KEY not configured")
    return {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }


def extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    output = data.get("output") or []
    parts: list[str] = []
    for item in output:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
    return "".join(parts)


async def chat_responses(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
) -> str:
    settings = get_settings()
    payload = {
        "model": model or settings.openai_voice_model,
        "input": messages,
        "max_output_tokens": max_tokens,
        "temperature": temperature,
        "store": False,
    }
    async with http_client(timeout=20.0) as client:
        res = await client.post(
            "https://api.openai.com/v1/responses",
            json=payload,
            headers=_auth_headers(),
        )
    if res.status_code != 200:
        raise HTTPException(502, f"OpenAI error {res.status_code}: {res.text[:200]}")
    return extract_response_text(res.json()).strip()


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1, bits: int = 16) -> bytes:
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits,
        b"data",
        len(pcm),
    )
    return header + pcm


async def transcribe_whisper(
    audio: bytes,
    *,
    sample_rate: int = 16000,
    language: str = "en",
) -> tuple[str, float | None]:

    wav = pcm_to_wav(audio, sample_rate)
    settings = get_settings()
    lang = None if language == "multi" else language.split("-")[0]
    data: dict[str, Any] = {"model": "whisper-1", "response_format": "json"}
    if lang:
        data["language"] = lang
    files = {"file": ("audio.wav", wav, "audio/wav")}
    async with http_client(timeout=60.0) as client:
        res = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
    if res.status_code != 200:
        raise HTTPException(502, f"Whisper error {res.status_code}: {res.text[:200]}")
    body = res.json()
    return body.get("text", "").strip(), None


async def tts_speech(
    text: str,
    *,
    voice: str = "alloy",
    model: str = "gpt-4o-mini-tts",
) -> bytes:
    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "mp3",
    }
    async with http_client(timeout=60.0) as client:
        res = await client.post(
            "https://api.openai.com/v1/audio/speech",
            json=payload,
            headers=_auth_headers(),
        )
    if res.status_code != 200:
        raise HTTPException(502, f"OpenAI TTS error {res.status_code}: {res.text[:200]}")
    return res.content


async def tts_whisper_timestamps(
    text: str,
    *,
    voice: str = "alloy",
) -> tuple[bytes, list[dict[str, Any]]]:
    audio = await tts_speech(text, voice=voice)
    settings = get_settings()

    files = {"file": ("speech.mp3", audio, "audio/mpeg")}
    data = {
        "model": "whisper-1",
        "response_format": "verbose_json",
        "timestamp_granularities[]": "word",
    }
    async with http_client(timeout=60.0) as client:
        res = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            data=data,
            files=files,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
    if res.status_code != 200:
        return audio, []
    body = res.json()
    return audio, body.get("words") or []


def audio_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dims (matches rag_chunks.embedding)


async def embed(text: str, *, model: str = EMBEDDING_MODEL) -> list[float]:
    """Return the embedding vector for a single text."""
    payload = {"model": model, "input": text[:8000]}
    async with http_client(timeout=20.0) as client:
        res = await client.post(
            "https://api.openai.com/v1/embeddings",
            json=payload,
            headers=_auth_headers(),
        )
    if res.status_code != 200:
        raise HTTPException(502, f"OpenAI embeddings error {res.status_code}: {res.text[:200]}")
    return res.json()["data"][0]["embedding"]


async def embed_batch(texts: list[str], *, model: str = EMBEDDING_MODEL) -> list[list[float]]:
    """Return embeddings for many texts in one request (order preserved)."""
    if not texts:
        return []
    payload = {"model": model, "input": [t[:8000] for t in texts]}
    async with http_client(timeout=30.0) as client:
        res = await client.post(
            "https://api.openai.com/v1/embeddings",
            json=payload,
            headers=_auth_headers(),
        )
    if res.status_code != 200:
        raise HTTPException(502, f"OpenAI embeddings error {res.status_code}: {res.text[:200]}")
    rows = sorted(res.json().get("data") or [], key=lambda d: d.get("index", 0))
    return [r["embedding"] for r in rows]
