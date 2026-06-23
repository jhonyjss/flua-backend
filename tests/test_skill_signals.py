"""Unit tests for the deterministic skill-scoring engine (pure functions)."""

from app.services.ai.skill_signals import (
    Turn,
    compute_deterministic,
    comprehension_signal,
    confidence_for,
    conversation_signal,
    grammar_signal,
    pronunciation_signal,
    vocabulary_signal,
)


# ── vocabulary ─────────────────────────────────────────────────────────────


def test_vocabulary_rewards_target_coverage():
    target = ["prefer", "rather", "favorite"]
    high = vocabulary_signal("I prefer tea and my favorite drink, I would rather walk", target)
    low = vocabulary_signal("yes no maybe", target)
    assert high > low
    assert high >= 55


def test_vocabulary_handles_multiword_targets_and_accents():
    # accent-folded substring match
    assert vocabulary_signal("eu gosto de cafe", ["café"]) > 0


def test_vocabulary_without_targets_uses_variety_only():
    varied = vocabulary_signal(
        "morning coffee breakfast train office meeting lunch project deadline evening",
        [],
    )
    sparse = vocabulary_signal("the the the a a is is", [])
    assert varied > sparse


# ── grammar ────────────────────────────────────────────────────────────────


def test_grammar_no_corrections_is_perfect():
    assert grammar_signal(corrections_received=0, student_turn_count=8) == 100


def test_grammar_drops_with_more_corrections():
    clean = grammar_signal(0, 8)
    messy = grammar_signal(8, 8)
    assert messy < clean


def test_grammar_blends_phrase_scores():
    blended = grammar_signal(0, 6, phrase_scores=[40, 50, 60])
    assert blended < 100  # phrase scores pull the perfect corrections score down


# ── pronunciation ──────────────────────────────────────────────────────────


def test_pronunciation_uses_stt_confidence_when_present():
    score, is_proxy = pronunciation_signal(stt_confidence=0.92)
    assert score == 92
    assert is_proxy is False


def test_pronunciation_proxies_from_phrase_scores():
    score, is_proxy = pronunciation_signal(phrase_scores=[80, 70])
    assert score == 75
    assert is_proxy is True


def test_pronunciation_neutral_proxy_without_data():
    score, is_proxy = pronunciation_signal()
    assert score == 50
    assert is_proxy is True


# ── conversation ───────────────────────────────────────────────────────────


def test_conversation_zero_turns():
    assert conversation_signal([], help_requests=0, completion_rate=0.0) == 0


def test_conversation_rich_beats_sparse():
    rich = [Turn("student", "I usually wake up early and go to the office by train") for _ in range(8)]
    sparse = [Turn("student", "yes"), Turn("student", "no")]
    assert conversation_signal(rich, 0, 1.0) > conversation_signal(sparse, 0, 0.2)


def test_conversation_help_requests_penalize():
    turns = [Turn("student", "I think the weather is nice today and warm") for _ in range(6)]
    assert conversation_signal(turns, help_requests=4, completion_rate=0.5) < conversation_signal(
        turns, help_requests=0, completion_rate=0.5
    )


# ── comprehension ──────────────────────────────────────────────────────────


def test_comprehension_high_without_confusion():
    turns = [Turn("student", "Yes, I like reading books in the evening")]
    assert comprehension_signal(turns) == 100


def test_comprehension_drops_with_confusion_markers():
    turns = [
        Turn("student", "sorry, can you repeat?"),
        Turn("student", "não entendi, de novo"),
        Turn("student", "I like coffee"),
    ]
    assert comprehension_signal(turns) < 100


def test_comprehension_empty_is_neutral():
    assert comprehension_signal([]) == 50


# ── confidence ─────────────────────────────────────────────────────────────


def test_confidence_scales_with_turns():
    assert confidence_for(0) == 0.0
    assert confidence_for(6) == 0.5
    assert confidence_for(12) == 1.0
    assert confidence_for(30) == 1.0


# ── integration ────────────────────────────────────────────────────────────


def test_compute_deterministic_shape_and_ranges():
    turns = [
        {"role": "tutor", "text": "What do you prefer, tea or coffee?"},
        {"role": "student", "text": "I prefer tea to coffee, it is my favorite"},
        {"role": "tutor", "text": "Great! And in the morning?"},
        {"role": "student", "text": "In the morning I would rather drink water"},
    ]
    result = compute_deterministic(
        turns,
        target_vocab=["prefer", "rather", "favorite"],
        corrections_received=1,
        completion_rate=0.75,
    )
    for key in ("grammar", "vocabulary", "pronunciation", "conversation", "comprehension"):
        assert 0 <= result[key] <= 100, key
    assert result["turns_count"] == 2
    assert 0.0 <= result["confidence"] <= 1.0
    # No STT/phrase data → pronunciation is a low-confidence proxy.
    assert result["pronunciation_is_proxy"] is True
    # Good vocabulary coverage should score decently.
    assert result["vocabulary"] >= 45


def test_compute_deterministic_strong_vs_weak_student():
    strong = compute_deterministic(
        [{"role": "student", "text": "I prefer tea and my favorite hobby is reading every evening"}] * 8,
        target_vocab=["prefer", "favorite"],
        corrections_received=0,
        completion_rate=1.0,
    )
    weak = compute_deterministic(
        [{"role": "student", "text": "sorry repeat"}, {"role": "student", "text": "no"}],
        target_vocab=["prefer", "favorite"],
        corrections_received=5,
        completion_rate=0.0,
    )
    assert strong["conversation"] > weak["conversation"]
    assert strong["comprehension"] > weak["comprehension"]
    assert strong["vocabulary"] > weak["vocabulary"]
    assert strong["confidence"] > weak["confidence"]
