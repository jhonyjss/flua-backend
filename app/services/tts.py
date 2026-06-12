"""TTS providers (Google / ElevenLabs / OpenAI / Deepgram).

Ported from server/api/avatar/speak.post.ts: voice maps, char limits and
sentence-boundary chunking. MP3 chunks are concatenated byte-wise.
"""
import base64
import re

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client

ELEVENLABS_VOICES = {
    "sarah": "VslWhLYTjGjfnDx9VCj3",
    "james": "VR6AewLTigWG4xSOukaG",
    "emily": "LcfcDJNUP1GQjkzn1xUU",
    "default": "VslWhLYTjGjfnDx9VCj3",
}

OPENAI_VOICES = {"sarah": "nova", "james": "onyx", "emily": "shimmer", "default": "nova"}
OPENAI_DIRECT_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"}

DEEPGRAM_VOICES = {
    "sarah": "aura-2-asteria-en",
    "james": "aura-2-orion-en",
    "emily": "aura-2-luna-en",
    "default": "aura-2-asteria-en",
}

GOOGLE_VOICES = {
    "sarah": {"name": "en-US-Studio-O", "ssmlGender": "FEMALE"},
    "james": {"name": "en-US-Studio-M", "ssmlGender": "MALE"},
    "emily": {"name": "en-US-Neural2-F", "ssmlGender": "FEMALE"},
    "default": {"name": "en-US-Studio-O", "ssmlGender": "FEMALE"},
    "pt_female": {"name": "pt-BR-Standard-D", "ssmlGender": "FEMALE"},
    "pt_male": {"name": "pt-BR-Neural2-B", "ssmlGender": "MALE"},
}

CHIRP3_HD_CHARACTERS = {"Puck", "Charon", "Fenrir", "Orus", "Aoede", "Kore", "Leda", "Zephyr"}

TTS_CHAR_LIMITS = {
    "google": 4800,
    "elevenlabs": 4800,
    "openai": 4000,
    "deepgram": 4800,
}


def split_text_for_tts(text: str, max_chars: int) -> list[str]:
    """Split at sentence boundaries so each chunk fits the provider limit."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        # A single sentence longer than the limit gets hard-split on spaces.
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            piece, sentence = sentence[:cut], sentence[cut:].lstrip()
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece)
        if len(current) + len(sentence) + 1 > max_chars:
            if current:
                chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def resolve_google_voice(voice_id: str, language_code: str) -> dict:
    """Resolve named voices, Chirp3 HD characters (chirp3hd_X) and raw names."""
    if voice_id.startswith("chirp3hd_"):
        character = voice_id.removeprefix("chirp3hd_")
        if character in CHIRP3_HD_CHARACTERS:
            return {"name": f"{language_code}-Chirp3-HD-{character}", "ssmlGender": "FEMALE"}
    if voice_id in GOOGLE_VOICES:
        return GOOGLE_VOICES[voice_id]
    if re.match(r"^[a-z]{2}-[A-Z]{2}-", voice_id):
        return {"name": voice_id, "ssmlGender": "FEMALE"}
    return GOOGLE_VOICES["default"]


async def synthesize(text: str, provider: str, voice_id: str, language_code: str) -> bytes:
    """Synthesize full text (chunked) with the given provider; returns MP3 bytes."""
    limit = TTS_CHAR_LIMITS.get(provider, 4000)
    chunks = split_text_for_tts(text, limit)
    if not chunks:
        raise HTTPException(400, "Empty text")
    audio = b""
    for chunk in chunks:
        audio += await _synthesize_chunk(chunk, provider, voice_id, language_code)
    return audio


async def _synthesize_chunk(text: str, provider: str, voice_id: str, language_code: str) -> bytes:
    settings = get_settings()

    if provider == "google":
        if not settings.google_tts_api_key:
            raise HTTPException(500, "GOOGLE_TTS_API_KEY not configured")
        voice = resolve_google_voice(voice_id, language_code)
        async with http_client(timeout=30.0) as client:
            res = await client.post(
                f"https://texttospeech.googleapis.com/v1/text:synthesize?key={settings.google_tts_api_key}",
                json={
                    "input": {"text": text},
                    "voice": {"languageCode": language_code, "name": voice["name"]},
                    "audioConfig": {"audioEncoding": "MP3"},
                },
            )
        _raise_for_provider(res, "Google TTS")
        return base64.b64decode(res.json()["audioContent"])

    if provider == "elevenlabs":
        if not settings.elevenlabs_api_key:
            raise HTTPException(500, "ELEVENLABS_API_KEY not configured")
        voice = ELEVENLABS_VOICES.get(voice_id, voice_id if len(voice_id) > 10 else ELEVENLABS_VOICES["default"])
        async with http_client(timeout=60.0) as client:
            res = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                json={"text": text, "model_id": "eleven_multilingual_v2"},
                headers={"xi-api-key": settings.elevenlabs_api_key},
            )
        _raise_for_provider(res, "ElevenLabs")
        return res.content

    if provider == "openai":
        if not settings.openai_api_key:
            raise HTTPException(500, "OPENAI_API_KEY not configured")
        voice = voice_id if voice_id in OPENAI_DIRECT_VOICES else OPENAI_VOICES.get(voice_id, "nova")
        async with http_client(timeout=60.0) as client:
            res = await client.post(
                "https://api.openai.com/v1/audio/speech",
                json={"model": "gpt-4o-mini-tts", "voice": voice, "input": text, "response_format": "mp3"},
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            )
        _raise_for_provider(res, "OpenAI TTS")
        return res.content

    if provider == "deepgram":
        if not settings.deepgram_api_key:
            raise HTTPException(500, "DEEPGRAM_API_KEY not configured")
        voice = DEEPGRAM_VOICES.get(voice_id, DEEPGRAM_VOICES["default"])
        async with http_client(timeout=60.0) as client:
            res = await client.post(
                f"https://api.deepgram.com/v1/speak?model={voice}",
                json={"text": text},
                headers={"Authorization": f"Token {settings.deepgram_api_key}"},
            )
        _raise_for_provider(res, "Deepgram TTS")
        return res.content

    raise HTTPException(400, f"Unsupported TTS provider: {provider}")


def _raise_for_provider(res, label: str) -> None:
    if res.status_code != 200:
        raise HTTPException(502, f"{label} error {res.status_code}: {res.text[:200]}")
