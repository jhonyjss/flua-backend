"""Configurable thresholds for the speech correction pipeline.

Threshold rationale
-------------------
* ``min_dictionary_fuzzy_score`` (default 82): RapidFuzz ratio on a 0–100 scale.
  Below this, dictionary suggestions are too distant to trust for free speech.

* ``min_short_token_context_score`` (default 0.72): Short ASR fragments like
  ``r`` / ``u`` are ambiguous globally; we only rewrite them when expected-sentence
  or lesson-context alignment is strong.

* ``min_word_correction_score`` (default 0.58): Combined fuzzy + frequency +
  context score for normal-length tokens. Keeps unknown free speech from being
  aggressively "fixed" to unrelated dictionary words.

* ``expected_context_boost`` (default 0.35): Added to candidates that match the
  aligned expected word — enough to beat a slightly higher fuzzy dictionary hit
  when the lesson target is known.

* ``lesson_vocab_boost`` (default 0.22): Secondary boost for lesson vocabulary
  without full sentence alignment.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpeechPipelineConfig:
    dictionary_size: int = 200_000
    max_edit_distance: int = 2
    max_candidates_per_token: int = 24

    min_dictionary_fuzzy_score: float = 82.0
    min_short_token_context_score: float = 0.72
    min_word_correction_score: float = 0.58
    expected_context_boost: float = 0.35
    lesson_vocab_boost: float = 0.22

    fuzzy_weight: float = 0.50
    frequency_weight: float = 0.30
    context_weight: float = 0.20

    # Tokens with length <= this value use stricter short-token rules.
    short_token_max_len: int = 2

    # Whisper model id for faster-whisper (lazy-loaded).
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Known ASR shorthand → spoken-form expansions (candidates only).
    asr_shorthand_candidates: dict[str, list[str]] = field(
        default_factory=lambda: {
            "r": ["are"],
            "u": ["you"],
            "im": ["i'm", "i am"],
            "i m": ["i am", "i'm"],
            "ur": ["your", "you're", "you are"],
            "y": ["why"],
            "b": ["be"],
            "c": ["see", "sea"],
            "n": ["and", "in"],
            "wanna": ["want to"],
            "gonna": ["going to"],
            "gotta": ["got to"],
            "kinda": ["kind of"],
            "lemme": ["let me"],
            "dunno": ["do not know", "don't know"],
        }
    )
