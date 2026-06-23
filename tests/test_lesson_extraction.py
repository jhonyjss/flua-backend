"""Unit tests for the pure lesson vocabulary/error extraction parser."""

from app.services.ai.lesson_extraction import MAX_ERRORS, MAX_VOCAB, parse_extraction


def test_empty_or_invalid_input():
    assert parse_extraction(None) == ([], [])
    assert parse_extraction({}) == ([], [])
    assert parse_extraction({"vocabulary": "nope", "errors": 5}) == ([], [])


def test_parses_vocabulary_with_defaults_and_examples():
    vocab, errors = parse_extraction(
        {
            "vocabulary": [
                {"term": "give up", "type": "phrasal_verb", "meaning_pt": "desistir", "example": "Don't give up."},
                {"term": "house", "meaning_pt": "casa"},  # type defaults to word
                {"term": "  ", "meaning_pt": "x"},  # empty term dropped
            ]
        }
    )
    assert errors == []
    assert vocab[0] == {
        "term": "give up", "type": "phrasal_verb", "meaning_pt": "desistir", "examples": ["Don't give up."],
    }
    assert vocab[1]["type"] == "word"
    assert vocab[1]["examples"] == []
    assert len(vocab) == 2


def test_invalid_vocab_type_falls_back_to_word_and_dedupes():
    vocab, _ = parse_extraction(
        {
            "vocabulary": [
                {"term": "Run", "type": "bogus"},
                {"term": "run", "type": "word"},  # dup (case-insensitive, same resolved type)
            ]
        }
    )
    assert len(vocab) == 1
    assert vocab[0]["type"] == "word"


def test_parses_errors_accepting_error_or_error_text():
    _, errors = parse_extraction(
        {
            "errors": [
                {"error": "I has a dog", "correction": "I have a dog", "category": "grammar"},
                {"error_text": "make a party", "correction": "throw a party"},  # category defaults
                {"error": "x", "correction": ""},  # no correction → dropped
            ]
        }
    )
    assert errors[0]["error_text"] == "I has a dog"
    assert errors[0]["category"] == "grammar"
    assert errors[1]["category"] == "other"
    assert len(errors) == 2


def test_caps_respected():
    big_vocab = [{"term": f"w{i}", "type": "word"} for i in range(20)]
    big_errors = [{"error": f"e{i}", "correction": f"c{i}"} for i in range(20)]
    vocab, errors = parse_extraction({"vocabulary": big_vocab, "errors": big_errors})
    assert len(vocab) == MAX_VOCAB
    assert len(errors) == MAX_ERRORS
