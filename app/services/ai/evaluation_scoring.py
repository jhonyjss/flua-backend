"""Pure scoring helpers for the hybrid lesson evaluation.

Combines the deterministic signals (`skill_signals`) with the LLM judge scores
into the final per-skill values. Kept free of FastAPI/HTTP imports so it stays
fast and unit-testable (stdlib only).
"""

from __future__ import annotations

# Final score = w_det · deterministic + w_llm · llm_judge, per skill.
# The deterministic weight is higher where an objective signal is strong
# (vocabulary coverage, STT confidence) and lower where nuance dominates
# (grammar correctness, comprehension of intent).
WEIGHTS: dict[str, tuple[float, float]] = {
    "grammar": (0.3, 0.7),
    "vocabulary": (0.6, 0.4),
    "pronunciation": (0.7, 0.3),
    "conversation": (0.5, 0.5),
    "comprehension": (0.4, 0.6),
}
SKILLS: tuple[str, ...] = tuple(WEIGHTS.keys())

PROMPT_VERSION = 1

# Below this many student turns the sample is too small to be meaningful.
MIN_STUDENT_TURNS = 4


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def completion_rate(objectives_completed: int, objectives_total: int) -> float:
    """Objectives completed / total, clamped to 0–1."""
    if objectives_total <= 0:
        return 0.0
    return max(0.0, min(1.0, objectives_completed / objectives_total))


def should_skip(student_turn_count: int) -> bool:
    """Too few turns → don't evaluate (scores would be noise)."""
    return student_turn_count < MIN_STUDENT_TURNS


def sanitize_llm_scores(data: dict) -> dict[str, int]:
    """Keep only the valid 0–100 skill scores the judge returned."""
    out: dict[str, int] = {}
    for skill in SKILLS:
        value = data.get(skill)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[skill] = _clamp(value)
    return out


def blend(deterministic: dict, llm: dict) -> dict[str, int]:
    """Weighted blend per skill. Missing LLM score → falls back to the
    deterministic value (so the LLM failing never zeroes a skill)."""
    out: dict[str, int] = {}
    for skill, (w_det, w_llm) in WEIGHTS.items():
        det_value = _clamp(deterministic.get(skill, 50))
        llm_value = llm.get(skill)
        llm_value = _clamp(llm_value) if isinstance(llm_value, (int, float)) and not isinstance(llm_value, bool) else det_value
        out[skill] = _clamp(w_det * det_value + w_llm * llm_value)
    return out
