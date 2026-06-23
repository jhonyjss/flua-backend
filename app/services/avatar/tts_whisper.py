"""TTS + Whisper timestamps for TalkingHead lip-sync."""
from __future__ import annotations

from app.schemas.avatar import TtsWhisperRequest, TtsWhisperResult
from app.services.openai_client import audio_base64, tts_whisper_timestamps


def _estimate_timing(text: str, audio_len: int) -> tuple[list[str], list[float], list[float]]:
    words = [w for w in text.split() if w]
    if not words:
        return [], [], []
    duration_ms = (audio_len / 16000) * 1000
    ms_per_word = duration_ms / max(len(words), 1)
    wtimes = [round(i * ms_per_word) for i in range(len(words))]
    wdurations = [round(ms_per_word) for _ in words]
    return words, wtimes, wdurations


async def tts_whisper(req: TtsWhisperRequest) -> TtsWhisperResult:
    text = req.text.strip()
    voice = req.voiceId or "nova"
    try:
        audio, whisper_words = await tts_whisper_timestamps(text, voice=voice)
    except Exception as exc:
        return TtsWhisperResult(success=False, words=[], wtimes=[], wdurations=[], provider="browser", error=str(exc))

    words: list[str] = []
    wtimes: list[float] = []
    wdurations: list[float] = []

    if whisper_words:
        for w in whisper_words:
            word = str(w.get("word", "")).strip()
            if not word:
                continue
            start = float(w.get("start", 0))
            end = float(w.get("end", start))
            words.append(word)
            wtimes.append(round(start * 1000))
            wdurations.append(round((end - start) * 1000))

    if not words:
        words, wtimes, wdurations = _estimate_timing(text, len(audio))

    return TtsWhisperResult(
        success=True,
        audioBase64=audio_base64(audio),
        words=words,
        wtimes=wtimes,
        wdurations=wdurations,
        provider="openai",
    )
