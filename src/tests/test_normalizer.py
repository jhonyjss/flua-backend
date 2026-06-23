"""Tests for text normalization and ASR shorthand candidates."""
from speech.config import SpeechPipelineConfig
from speech.normalizer import (
    get_asr_shorthand_candidates,
    normalize_text,
    tokenize,
)


def test_normalize_lowercase_and_punctuation():
    assert normalize_text("  How ARE You?!  ") == "how are you"


def test_tokenize_splits_words():
    assert tokenize("How are you?") == ["how", "are", "you"]


def test_asr_shorthand_candidates_are_not_forced():
    cfg = SpeechPipelineConfig()
    assert "are" in get_asr_shorthand_candidates("r", cfg)
    assert "you" in get_asr_shorthand_candidates("u", cfg)
    assert "i am" in get_asr_shorthand_candidates("im", cfg)
    assert "want to" in get_asr_shorthand_candidates("wanna", cfg)
    assert "going to" in get_asr_shorthand_candidates("gonna", cfg)


def test_unknown_token_has_no_shorthand_candidates():
    assert get_asr_shorthand_candidates("xylophone") == []
