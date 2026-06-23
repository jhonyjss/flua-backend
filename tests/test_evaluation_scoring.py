"""Unit tests for the pure hybrid-blend scoring helpers."""

from app.services.ai.evaluation_scoring import (
    SKILLS,
    WEIGHTS,
    blend,
    completion_rate,
    sanitize_llm_scores,
    should_skip,
)


def test_weights_sum_to_one_per_skill():
    for skill, (w_det, w_llm) in WEIGHTS.items():
        assert abs((w_det + w_llm) - 1.0) < 1e-9, skill


def test_blend_uses_weights():
    det = dict.fromkeys(SKILLS, 80)
    llm = dict.fromkeys(SKILLS, 60)
    out = blend(det, llm)
    # grammar weights (0.3 det, 0.7 llm): 0.3*80 + 0.7*60 = 66
    assert out["grammar"] == 66
    # vocabulary weights (0.6 det, 0.4 llm): 0.6*80 + 0.4*60 = 72
    assert out["vocabulary"] == 72


def test_blend_falls_back_to_deterministic_when_llm_missing():
    det = {"grammar": 70, "vocabulary": 55, "pronunciation": 40, "conversation": 65, "comprehension": 80}
    assert blend(det, {}) == det  # no LLM → deterministic passes through


def test_blend_clamps_and_ignores_bad_llm_values():
    det = dict.fromkeys(SKILLS, 50)
    llm = {"grammar": 999, "vocabulary": "high", "pronunciation": True}
    out = blend(det, llm)
    # 999 clamps to 100 → 0.3*50 + 0.7*100 = 85
    assert out["grammar"] == 85
    # non-numeric / bool fall back to deterministic 50
    assert out["vocabulary"] == 50
    assert out["pronunciation"] == 50


def test_sanitize_llm_scores():
    data = {"grammar": 80.4, "vocabulary": -5, "pronunciation": "x", "conversation": True, "extra": 1}
    out = sanitize_llm_scores(data)
    assert out["grammar"] == 80
    assert out["vocabulary"] == 0       # clamped
    assert "pronunciation" not in out   # non-numeric dropped
    assert "conversation" not in out    # bool dropped
    assert "extra" not in out           # not a skill


def test_completion_rate():
    assert completion_rate(0, 0) == 0.0
    assert completion_rate(3, 4) == 0.75
    assert completion_rate(5, 4) == 1.0  # clamped


def test_should_skip_threshold():
    assert should_skip(0) is True
    assert should_skip(3) is True
    assert should_skip(4) is False
    assert should_skip(12) is False
