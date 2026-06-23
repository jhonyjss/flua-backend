"""Spaced repetition (SM-2-lite) for vocabulary and recurring errors.

Pure & side-effect free so it stays fast and unit-testable. The caller turns the
returned `interval_days` into a concrete `next_review_at = now + interval_days`
and persists the new state.

`quality` is the student's recall on a 0–5 scale (Anki/SM-2 convention):
  0 = errou totalmente · 3 = lembrou com esforço · 5 = lembrou fácil.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

MIN_EASE = 1.3
DEFAULT_EASE = 2.5
PASS_THRESHOLD = 3  # quality >= 3 counts as a successful recall

Status = str  # 'new' | 'learning' | 'reviewing' | 'mastered'


@dataclass(frozen=True)
class SrsState:
    ease: float = DEFAULT_EASE
    interval_days: int = 0
    reps: int = 0
    lapses: int = 0
    confidence: float = 0.30
    status: Status = "new"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def status_for(confidence: float, reps: int, lapses_just_now: bool) -> Status:
    """Derive the learning status from recall history."""
    if lapses_just_now:
        return "learning"
    if confidence >= 0.85 and reps >= 4:
        return "mastered"
    if confidence >= 0.55 and reps >= 2:
        return "reviewing"
    if reps >= 1:
        return "learning"
    return "new"


def review(state: SrsState, quality: int) -> SrsState:
    """Apply one review outcome and return the new SRS state (SM-2-lite)."""
    q = max(0, min(5, int(quality)))
    passed = q >= PASS_THRESHOLD

    # Ease factor (SM-2 formula), floored so cards never collapse to daily forever.
    new_ease = state.ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ease = max(MIN_EASE, round(new_ease, 2))

    if not passed:
        # Lapse: reset the interval, drop confidence, schedule for tomorrow.
        reps = 0
        lapses = state.lapses + 1
        interval = 1
        confidence = _clamp01(state.confidence * 0.5)
        status = status_for(confidence, reps, lapses_just_now=True)
        return SrsState(new_ease, interval, reps, lapses, round(confidence, 2), status)

    reps = state.reps + 1
    if reps == 1:
        interval = 1
    elif reps == 2:
        interval = 6
    else:
        interval = max(1, round(state.interval_days * new_ease))

    # Confidence: EWMA toward the normalized quality (smoother than a hard set).
    target = q / 5.0
    confidence = _clamp01(0.6 * state.confidence + 0.4 * target)
    status = status_for(confidence, reps, lapses_just_now=False)
    return SrsState(new_ease, interval, reps, state.lapses, round(confidence, 2), status)


def calculate_next_review(confidence: float, mistakes: int) -> timedelta:
    """Simple heuristic fallback (matches the spec) — used when no SRS state
    exists yet, e.g. a brand-new item with only a confidence guess."""
    if confidence < 0.4:
        return timedelta(days=1)
    if mistakes > 2:
        return timedelta(days=2)
    if confidence < 0.7:
        return timedelta(days=3)
    return timedelta(days=7)
