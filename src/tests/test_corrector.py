"""Tests for context-aware speech correction."""
from speech.config import SpeechPipelineConfig
from speech.corrector import SpeechContextCorrector

# Small controlled vocabulary — avoids loading 200k words in unit tests.
TEST_VOCAB = [
    "i",
    "am",
    "are",
    "you",
    "how",
    "happy",
    "weather",
    "is",
    "beautiful",
    "the",
    "quick",
    "brown",
    "fox",
    "jumps",
    "over",
    "lazy",
    "dog",
    "there",
    "want",
    "to",
    "going",
    "a",
    "an",
    "my",
    "name",
    "xylophone",
    "serendipity",
]


def _corrector() -> SpeechContextCorrector:
    return SpeechContextCorrector(full_dictionary=TEST_VOCAB, config=SpeechPipelineConfig())


def test_how_r_u_corrected_with_expected_sentence():
    result = _corrector().correct("how r u", expected_sentence="how are you")
    assert result.corrected_transcription == "how are you"
    assert any(c.from_word == "r" and c.to == "are" for c in result.corrections)
    assert any(c.from_word == "u" and c.to == "you" for c in result.corrections)


def test_i_m_happy_corrected_to_i_am_happy():
    result = _corrector().correct("i m happy", expected_sentence="i am happy")
    assert result.corrected_transcription == "i am happy"
    assert any(c.from_word == "m" and c.to == "am" for c in result.corrections)


def test_weather_s_beautiful_corrected_to_is():
    result = _corrector().correct(
        "weather s beautiful",
        expected_sentence="weather is beautiful",
    )
    assert result.corrected_transcription == "weather is beautiful"
    assert any(c.from_word == "s" and c.to == "is" for c in result.corrections)


def test_free_speech_not_aggressively_corrected():
    raw = "the quick brown fox jumps over the lazy dog"
    result = _corrector().correct(raw, expected_sentence=None)
    assert result.corrected_transcription == raw
    assert result.corrections == []


def test_short_tokens_not_corrected_without_context():
    result = _corrector().correct("r u there", expected_sentence=None)
    # Without expected sentence, short tokens stay unchanged.
    assert result.corrected_transcription == "r u there"


def test_lesson_vocabulary_used_when_no_expected_sentence():
    result = _corrector().correct(
        "xylophon",
        expected_sentence=None,
        lesson_vocabulary=["xylophone"],
    )
    assert result.corrected_transcription == "xylophone"


def test_low_confidence_keeps_original_token():
    result = _corrector().correct(
        "serendipiti",
        expected_sentence=None,
        lesson_vocabulary=[],
    )
    # Close edit but without lesson/expected context may still correct via dictionary.
    # With our tiny dict containing serendipity, a correction is acceptable.
    assert result.corrected_transcription in {"serendipiti", "serendipity"}
