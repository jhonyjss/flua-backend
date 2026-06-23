"""Pydantic request/response schemas for the speech correction API."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SpeechCorrectionRequest(BaseModel):
    audio_url: str | None = None
    audio_base64: str | None = None
    raw_transcription: str | None = None
    expected_sentence: str | None = None
    lesson_vocabulary: list[str] | None = None
    lesson_id: str | None = None

    @model_validator(mode="after")
    def require_audio_or_transcript(self) -> "SpeechCorrectionRequest":
        if not self.raw_transcription and not self.audio_url and not self.audio_base64:
            raise ValueError("Provide raw_transcription or audio_url or audio_base64")
        return self


CorrectionReason = Literal[
    "expected_sentence_context",
    "lesson_vocabulary",
    "dictionary_match",
    "asr_shorthand",
    "contraction_normalization",
    "unchanged_low_confidence",
]


class CorrectionDetail(BaseModel):
    from_word: str = Field(alias="from")
    to: str
    reason: CorrectionReason
    score: float | None = None

    model_config = {"populate_by_name": True}


class SpeechCorrectionResponse(BaseModel):
    raw_transcription: str
    corrected_transcription: str
    expected_sentence: str | None = None
    score: float | None = None
    corrections: list[CorrectionDetail] = Field(default_factory=list)
    feedback: str = ""
    missing_words: list[str] = Field(default_factory=list)
    incorrect_words: list[str] = Field(default_factory=list)
