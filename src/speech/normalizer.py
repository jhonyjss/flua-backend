"""Text normalization and ASR shorthand candidate generation."""
from __future__ import annotations

import re
import unicodedata

from speech.config import SpeechPipelineConfig

# Punctuation removed except apostrophes inside contractions.
_PUNCT_RE = re.compile(r"[^\w\s']", re.UNICODE)
_MULTI_SPACE_RE = re.compile(r"\s+")

# Canonical contraction expansions used as *candidates*, not forced replacements.
_CONTRACTION_CANDIDATES: dict[str, list[str]] = {
    "i'm": ["i am"],
    "you're": ["you are"],
    "we're": ["we are"],
    "they're": ["they are"],
    "he's": ["he is", "he has"],
    "she's": ["she is", "she has"],
    "it's": ["it is", "it has"],
    "that's": ["that is", "that has"],
    "there's": ["there is", "there has"],
    "what's": ["what is", "what has"],
    "who's": ["who is", "who has"],
    "can't": ["cannot", "can not"],
    "won't": ["will not"],
    "don't": ["do not"],
    "doesn't": ["does not"],
    "didn't": ["did not"],
    "isn't": ["is not"],
    "aren't": ["are not"],
    "wasn't": ["was not"],
    "weren't": ["were not"],
    "haven't": ["have not"],
    "hasn't": ["has not"],
    "hadn't": ["had not"],
    "wouldn't": ["would not"],
    "couldn't": ["could not"],
    "shouldn't": ["should not"],
    "i've": ["i have"],
    "you've": ["you have"],
    "we've": ["we have"],
    "they've": ["they have"],
    "i'll": ["i will"],
    "you'll": ["you will"],
    "we'll": ["we will"],
    "they'll": ["they will"],
    "i'd": ["i would", "i had"],
    "you'd": ["you would", "you had"],
}


def normalize_text(text: str) -> str:
    """Lowercase, strip accents, remove stray punctuation, collapse whitespace."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    return normalized.split() if normalized else []


def get_asr_shorthand_candidates(
    token: str,
    config: SpeechPipelineConfig | None = None,
) -> list[str]:
    """Return extra candidates for common ASR truncations (never auto-replace)."""
    cfg = config or SpeechPipelineConfig()
    token = token.lower().strip()
    candidates: list[str] = []

    if token in cfg.asr_shorthand_candidates:
        candidates.extend(cfg.asr_shorthand_candidates[token])

    if token in _CONTRACTION_CANDIDATES:
        candidates.extend(_CONTRACTION_CANDIDATES[token])

    # Preserve order, dedupe.
    seen: set[str] = set()
    unique: list[str] = []
    for word in candidates:
        if word not in seen:
            seen.add(word)
            unique.append(word)
    return unique


def expand_multi_token_shorthands(tokens: list[str], config: SpeechPipelineConfig | None = None) -> list[list[str]]:
    """Per-token candidate lists including the original token."""
    cfg = config or SpeechPipelineConfig()
    result: list[list[str]] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        group = [token]

        # Handle split contractions like ["i", "m"] → candidate "i am".
        if i + 1 < len(tokens):
            pair = f"{token} {tokens[i + 1]}"
            pair_candidates = get_asr_shorthand_candidates(pair, cfg)
            if pair_candidates:
                group.extend(pair_candidates)

        group.extend(get_asr_shorthand_candidates(token, cfg))
        # Dedupe while preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for item in group:
            if item not in seen:
                seen.add(item)
                deduped.append(item)
        result.append(deduped)
        i += 1
    return result
