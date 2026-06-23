"""End-to-end speech correction pipeline orchestration."""
from __future__ import annotations

import logging

from speech.asr import get_whisper_asr, transcribe_audio_url
from speech.config import SpeechPipelineConfig
from speech.corrector import SpeechContextCorrector
from speech.dictionary import get_dictionary
from speech.schemas import SpeechCorrectionRequest, SpeechCorrectionResponse
from speech.scorer import score_transcription

logger = logging.getLogger(__name__)


async def run_speech_pipeline(
    request: SpeechCorrectionRequest,
    *,
    config: SpeechPipelineConfig | None = None,
) -> SpeechCorrectionResponse:
    """Run ASR (optional) → normalize → correct → score → feedback."""
    cfg = config or SpeechPipelineConfig()
    raw = (request.raw_transcription or "").strip()

    if not raw:
        raw = await _resolve_transcription(request, cfg)

    dictionary = get_dictionary(
        dictionary_size=cfg.dictionary_size,
        max_edit_distance=cfg.max_edit_distance,
    )
    corrector = SpeechContextCorrector(full_dictionary=dictionary, config=cfg)
    result = corrector.correct(
        raw_transcription=raw,
        expected_sentence=request.expected_sentence,
        lesson_vocabulary=request.lesson_vocabulary,
    )

    score_result = score_transcription(
        request.expected_sentence,
        result.corrected_transcription,
    )

    return SpeechCorrectionResponse(
        raw_transcription=result.raw_transcription,
        corrected_transcription=result.corrected_transcription,
        expected_sentence=request.expected_sentence,
        score=round(score_result.accuracy, 4) if request.expected_sentence else None,
        corrections=result.corrections,
        feedback=score_result.feedback,
        missing_words=score_result.missing_words,
        incorrect_words=score_result.incorrect_words,
    )


async def _resolve_transcription(
    request: SpeechCorrectionRequest,
    config: SpeechPipelineConfig,
) -> str:
    if request.audio_base64:
        asr = get_whisper_asr(
            model_size=config.whisper_model_size,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
        )
        return asr.transcribe_base64(request.audio_base64)

    if request.audio_url:
        return await transcribe_audio_url(request.audio_url)

    raise ValueError("No transcription source available")
