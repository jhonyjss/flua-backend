"""Tests for WER scoring and feedback."""
from speech.scorer import score_transcription


def test_perfect_match_scores_high():
    result = score_transcription("how are you", "how are you")
    assert result.accuracy >= 0.95
    assert result.missing_words == []
    assert "Excelente" in result.feedback


def test_partial_match_identifies_missing_words():
    result = score_transcription("how are you", "how you")
    assert 0.3 < result.accuracy < 1.0
    assert "are" in result.missing_words


def test_no_reference_returns_zero_accuracy():
    result = score_transcription(None, "hello world")
    assert result.accuracy == 0.0
    assert result.feedback
