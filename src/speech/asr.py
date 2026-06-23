"""Local ASR via faster-whisper (optional — skipped when raw_transcription is provided)."""
from __future__ import annotations

import base64
import logging
import tempfile
from functools import lru_cache
from pathlib import Path

from speech.config import SpeechPipelineConfig

logger = logging.getLogger(__name__)


class WhisperASR:
    """Lazy-loaded faster-whisper wrapper."""

    def __init__(self, config: SpeechPipelineConfig | None = None) -> None:
        self.config = config or SpeechPipelineConfig()
        self._model = None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed. "
                "Install speech extras or pass raw_transcription instead."
            ) from exc

        logger.info(
            "Loading Whisper model '%s' on %s",
            self.config.whisper_model_size,
            self.config.whisper_device,
        )
        self._model = WhisperModel(
            self.config.whisper_model_size,
            device=self.config.whisper_device,
            compute_type=self.config.whisper_compute_type,
        )
        return self._model

    def transcribe_file(self, path: str | Path, *, language: str = "en") -> str:
        model = self._ensure_model()
        segments, _info = model.transcribe(
            str(path),
            language=language,
            vad_filter=True,
            word_timestamps=False,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def transcribe_bytes(self, data: bytes, *, language: str = "en", suffix: str = ".wav") -> str:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            return self.transcribe_file(tmp.name, language=language)

    def transcribe_base64(self, audio_base64: str, *, language: str = "en") -> str:
        raw = base64.b64decode(audio_base64, validate=False)
        return self.transcribe_bytes(raw, language=language)


@lru_cache(maxsize=1)
def get_whisper_asr(
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
) -> WhisperASR:
    cfg = SpeechPipelineConfig(
        whisper_model_size=model_size,
        whisper_device=device,
        whisper_compute_type=compute_type,
    )
    return WhisperASR(cfg)


async def transcribe_audio_url(url: str, *, language: str = "en") -> str:
    """Download audio from URL and transcribe locally."""
    import httpx

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.content

    asr = get_whisper_asr()
    return asr.transcribe_bytes(data, language=language)
