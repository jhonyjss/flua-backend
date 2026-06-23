"""WER-based scoring and student feedback."""
from __future__ import annotations

from dataclasses import dataclass

from jiwer import Compose, RemovePunctuation, ToLowerCase, wer
from jiwer.process import process_words

from speech.normalizer import normalize_text, tokenize

_TRANSFORM = Compose([ToLowerCase(), RemovePunctuation()])


@dataclass(frozen=True)
class SpeechScoreResult:
    accuracy: float
    wer_value: float
    missing_words: list[str]
    incorrect_words: list[str]
    feedback: str


def _alignment_details(reference: str, hypothesis: str) -> tuple[list[str], list[str]]:
    """Extract missing and incorrect words via jiwer alignment."""
    missing: list[str] = []
    incorrect: list[str] = []

    try:
        out = process_words(reference, hypothesis)
    except Exception:
        return missing, incorrect

    ref_words = tokenize(reference)
    hyp_words = tokenize(hypothesis)

    for chunk in out.alignments[0]:
        if chunk.type == "delete":
            missing.extend(ref_words[chunk.ref_start_idx : chunk.ref_end_idx])
        elif chunk.type == "substitute":
            for i in range(chunk.ref_start_idx, chunk.ref_end_idx):
                ref_w = ref_words[i] if i < len(ref_words) else ""
                hyp_i = chunk.hyp_start_idx + (i - chunk.ref_start_idx)
                hyp_w = hyp_words[hyp_i] if hyp_i < len(hyp_words) else ""
                if ref_w and hyp_w and ref_w != hyp_w:
                    incorrect.append(f"{hyp_w}→{ref_w}")
        elif chunk.type == "insert":
            for i in range(chunk.hyp_start_idx, chunk.hyp_end_idx):
                hyp_w = hyp_words[i] if i < len(hyp_words) else ""
                if hyp_w:
                    incorrect.append(f"+{hyp_w}")

    return missing, incorrect


def score_transcription(
    reference: str | None,
    hypothesis: str,
    *,
    correct_threshold: float = 0.85,
    partial_threshold: float = 0.55,
) -> SpeechScoreResult:
    """Score hypothesis against reference; return accuracy in [0, 1]."""
    if not reference or not reference.strip():
        return SpeechScoreResult(
            accuracy=0.0,
            wer_value=1.0,
            missing_words=[],
            incorrect_words=[],
            feedback="Nenhuma frase esperada informada — pontuação não calculada.",
        )

    ref_norm = normalize_text(reference)
    hyp_norm = normalize_text(hypothesis)

    if not ref_norm:
        return SpeechScoreResult(
            accuracy=0.0,
            wer_value=1.0,
            missing_words=[],
            incorrect_words=[],
            feedback="Frase esperada vazia.",
        )

    if not hyp_norm:
        missing = tokenize(reference)
        return SpeechScoreResult(
            accuracy=0.0,
            wer_value=1.0,
            missing_words=missing,
            incorrect_words=[],
            feedback=_build_feedback(0.0, missing, [], correct_threshold, partial_threshold),
        )

    wer_value = float(wer(ref_norm, hyp_norm))
    accuracy = max(0.0, min(1.0, 1.0 - wer_value))
    missing, incorrect = _alignment_details(ref_norm, hyp_norm)
    feedback = _build_feedback(accuracy, missing, incorrect, correct_threshold, partial_threshold)

    return SpeechScoreResult(
        accuracy=accuracy,
        wer_value=wer_value,
        missing_words=missing,
        incorrect_words=incorrect,
        feedback=feedback,
    )


def _build_feedback(
    accuracy: float,
    missing: list[str],
    incorrect: list[str],
    correct_threshold: float,
    partial_threshold: float,
) -> str:
    if accuracy >= correct_threshold:
        return "Excelente! Sua pronúncia ficou muito próxima da frase esperada."

    if accuracy >= partial_threshold:
        focus_parts: list[str] = []
        if missing:
            focus_parts.append(f"palavras faltando: {', '.join(missing[:3])}")
        if incorrect:
            focus_parts.append(f"ajustes: {', '.join(incorrect[:3])}")
        if focus_parts:
            return f"Quase lá! Preste atenção em {'; '.join(focus_parts)}."
        return "Quase lá! Tente repetir com um pouco mais de clareza."

    if missing:
        return (
            f"Vamos praticar de novo. Preste atenção em: {', '.join(missing[:4])}."
        )
    return "Sem problema — vamos repetir a frase com calma."
