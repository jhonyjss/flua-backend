"""Pure parsing of the LLM judge's vocabulary/error extraction.

The lesson judge (evaluate_lesson) returns, alongside the scores, the new
vocabulary the student practised and the recurring mistakes it observed. This
module normalizes that raw JSON into clean dicts ready for persistence. It is
PURE (no I/O) so it can be unit-tested deterministically; persistence lives in
`learning_intel.save_lesson_extraction`.
"""

from __future__ import annotations

VOCAB_TYPES = {"word", "phrase", "collocation", "phrasal_verb", "idiom"}
ERROR_CATEGORIES = {"grammar", "vocabulary", "pronunciation", "other"}
MAX_VOCAB = 8
MAX_ERRORS = 6


def _clean(value: object, *, limit: int) -> str:
    return str(value).strip()[:limit] if value is not None else ""


def _examples(item: dict) -> list[str]:
    raw = item.get("examples")
    if isinstance(raw, list):
        out = [_clean(e, limit=200) for e in raw if str(e).strip()]
    else:
        single = _clean(item.get("example"), limit=200)
        out = [single] if single else []
    return out[:3]


def parse_extraction(data: dict | None) -> tuple[list[dict], list[dict]]:
    """Return (vocabulary, errors) normalized + deduped from the judge output.

    vocabulary item: {term, type, meaning_pt, examples}
    error item:      {error_text, correction, category, example_wrong, example_correct}
    """
    if not isinstance(data, dict):
        return [], []

    raw_vocab = data.get("vocabulary")
    raw_errors = data.get("errors")
    raw_vocab = raw_vocab if isinstance(raw_vocab, list) else []
    raw_errors = raw_errors if isinstance(raw_errors, list) else []

    vocab: list[dict] = []
    seen_terms: set[tuple[str, str]] = set()
    for item in raw_vocab:
        if not isinstance(item, dict):
            continue
        term = _clean(item.get("term"), limit=120)
        if not term:
            continue
        vtype = item.get("type") if item.get("type") in VOCAB_TYPES else "word"
        key = (term.lower(), vtype)
        if key in seen_terms:
            continue
        seen_terms.add(key)
        vocab.append(
            {
                "term": term,
                "type": vtype,
                "meaning_pt": _clean(item.get("meaning_pt"), limit=200) or None,
                "examples": _examples(item),
            }
        )
        if len(vocab) >= MAX_VOCAB:
            break

    errors: list[dict] = []
    seen_errors: set[tuple[str, str]] = set()
    for item in raw_errors:
        if not isinstance(item, dict):
            continue
        error_text = _clean(item.get("error") or item.get("error_text"), limit=300)
        correction = _clean(item.get("correction"), limit=300)
        if not error_text or not correction:
            continue
        key = (error_text.lower(), correction.lower())
        if key in seen_errors:
            continue
        seen_errors.add(key)
        category = item.get("category") if item.get("category") in ERROR_CATEGORIES else "other"
        errors.append(
            {
                "error_text": error_text,
                "correction": correction,
                "category": category,
                "example_wrong": _clean(item.get("example_wrong"), limit=300) or None,
                "example_correct": _clean(item.get("example_correct"), limit=300) or None,
            }
        )
        if len(errors) >= MAX_ERRORS:
            break

    return vocab, errors
