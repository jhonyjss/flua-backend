"""Context-aware speech transcription correction."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from rapidfuzz import fuzz

from speech.config import SpeechPipelineConfig
from speech.dictionary import EnglishDictionary, get_dictionary
from speech.normalizer import (
    expand_multi_token_shorthands,
    get_asr_shorthand_candidates,
    normalize_text,
    tokenize,
)
from speech.schemas import CorrectionDetail, CorrectionReason


@dataclass(frozen=True)
class CorrectionResult:
    raw_transcription: str
    corrected_transcription: str
    expected_sentence: str | None
    corrections: list[CorrectionDetail]
    tokens: list[str]


class SpeechContextCorrector:
    """Correct ASR output using lesson context, dictionary, and fuzzy scoring."""

    def __init__(
        self,
        full_dictionary: list[str] | EnglishDictionary | None = None,
        config: SpeechPipelineConfig | None = None,
    ) -> None:
        self.config = config or SpeechPipelineConfig()
        if isinstance(full_dictionary, EnglishDictionary):
            self.dictionary = full_dictionary
        elif full_dictionary:
            self.dictionary = EnglishDictionary(self.config)
            self.dictionary.load_from_words(list(full_dictionary))
        else:
            self.dictionary = get_dictionary(
                dictionary_size=self.config.dictionary_size,
                max_edit_distance=self.config.max_edit_distance,
            )

        self._lesson_vocab_set: set[str] = set()
        self._expected_tokens: list[str] = []
        self._expected_set: set[str] = set()

    def correct(
        self,
        raw_transcription: str,
        expected_sentence: str | None = None,
        lesson_vocabulary: list[str] | None = None,
    ) -> CorrectionResult:
        raw = raw_transcription.strip()
        normalized = normalize_text(raw)
        tokens = tokenize(raw)

        self._expected_tokens = tokenize(expected_sentence) if expected_sentence else []
        self._expected_set = set(self._expected_tokens)
        self._lesson_vocab_set = {
            normalize_text(w) for w in (lesson_vocabulary or []) if w.strip()
        }

        if not tokens:
            return CorrectionResult(
                raw_transcription=raw,
                corrected_transcription=normalized,
                expected_sentence=expected_sentence,
                corrections=[],
                tokens=[],
            )

        aligned_expected = (
            _align_expected_to_hypothesis(tokens, self._expected_tokens)
            if self._expected_tokens
            else [None] * len(tokens)
        )
        shorthand_groups = expand_multi_token_shorthands(tokens, self.config)

        corrected_tokens: list[str] = []
        corrections: list[CorrectionDetail] = []

        for idx, token in enumerate(tokens):
            expected_word = aligned_expected[idx]
            candidates = self._collect_candidates(
                token=token,
                shorthand_candidates=shorthand_groups[idx],
                expected_word=expected_word,
            )
            best_word, best_score, reason = self._pick_best_candidate(
                token=token,
                candidates=candidates,
                expected_word=expected_word,
            )

            corrected_tokens.append(best_word)
            if best_word != token:
                corrections.append(
                    CorrectionDetail(
                        **{
                            "from": token,
                            "to": best_word,
                            "reason": reason,
                            "score": round(best_score, 4),
                        }
                    )
                )

        corrected = " ".join(corrected_tokens)
        return CorrectionResult(
            raw_transcription=raw,
            corrected_transcription=corrected,
            expected_sentence=expected_sentence,
            corrections=corrections,
            tokens=corrected_tokens,
        )

    def _collect_candidates(
        self,
        token: str,
        shorthand_candidates: list[str],
        expected_word: str | None,
    ) -> dict[str, tuple[float, CorrectionReason]]:
        """Build a candidate → (base_score, reason) map."""
        candidates: dict[str, tuple[float, CorrectionReason]] = {token: (1.0, "unchanged_low_confidence")}

        for shorthand in shorthand_candidates:
            if shorthand != token:
                candidates[shorthand] = (0.80, "asr_shorthand")

        if expected_word and expected_word != token:
            candidates[expected_word] = (
                0.90 + self.config.expected_context_boost,
                "expected_sentence_context",
            )

        for vocab_word in self._lesson_vocab_set:
            if vocab_word == token:
                continue
            sim = fuzz.ratio(token, vocab_word) / 100.0
            if sim >= 0.65 or len(token) <= self.config.short_token_max_len:
                score = sim + self.config.lesson_vocab_boost
                prev = candidates.get(vocab_word)
                if not prev or score > prev[0]:
                    candidates[vocab_word] = (score, "lesson_vocabulary")

        dict_candidates = self.dictionary.get_candidates(token)
        for dict_word in dict_candidates[: self.config.max_candidates_per_token]:
            if dict_word == token:
                continue
            sim = fuzz.WRatio(token, dict_word) / 100.0
            freq = self.dictionary.frequency_score(dict_word)
            score = (
                sim * self.config.fuzzy_weight
                + freq * self.config.frequency_weight
            )
            prev = candidates.get(dict_word)
            if not prev or score > prev[0]:
                candidates[dict_word] = (score, "dictionary_match")

        return candidates

    def _pick_best_candidate(
        self,
        token: str,
        candidates: dict[str, tuple[float, CorrectionReason]],
        expected_word: str | None,
    ) -> tuple[str, float, CorrectionReason]:
        is_short = len(token) <= self.config.short_token_max_len

        best_word = token
        best_score = 0.0
        best_reason: CorrectionReason = "unchanged_low_confidence"

        for word, (score, reason) in candidates.items():
            if word == token:
                continue

            context_boost = 0.0
            if expected_word and word == expected_word:
                context_boost = self.config.expected_context_boost
            elif word in self._expected_set:
                context_boost = self.config.expected_context_boost * 0.85
            elif word in self._lesson_vocab_set:
                context_boost = self.config.lesson_vocab_boost

            combined = min(
                1.0,
                score
                + context_boost * self.config.context_weight
                + (fuzz.ratio(token, word) / 100.0) * 0.1,
            )

            if combined > best_score:
                best_word = word
                best_score = combined
                best_reason = reason

        threshold = (
            self.config.min_short_token_context_score
            if is_short
            else self.config.min_word_correction_score
        )

        # Short tokens require expected/lesson context unless match is overwhelming.
        if is_short and best_word != token:
            has_strong_context = (
                expected_word is not None
                and best_word == expected_word
            ) or best_word in self._expected_set
            if not has_strong_context and best_score < 0.90:
                return token, 1.0, "unchanged_low_confidence"

        if best_word != token and best_score < threshold:
            return token, 1.0, "unchanged_low_confidence"

        if best_word == token:
            return token, 1.0, "unchanged_low_confidence"

        return best_word, best_score, best_reason


def _align_expected_to_hypothesis(
    hypothesis: list[str],
    reference: list[str],
) -> list[str | None]:
    """Map each hypothesis token to the best matching expected word (if any)."""
    if not reference:
        return [None] * len(hypothesis)

    aligned: list[str | None] = [None] * len(hypothesis)
    matcher = SequenceMatcher(a=hypothesis, b=reference)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                aligned[i1 + offset] = reference[j1 + offset]
        elif tag == "replace":
            hyp_slice = hypothesis[i1:i2]
            ref_slice = reference[j1:j2]
            ref_assignments = _match_slices(hyp_slice, ref_slice)
            for offset, ref_word in enumerate(ref_assignments):
                aligned[i1 + offset] = ref_word
        elif tag == "delete":
            for offset in range(i2 - i1):
                aligned[i1 + offset] = None
        elif tag == "insert":
            continue

    return aligned


def _match_slices(hypothesis: list[str], reference: list[str]) -> list[str | None]:
    """Greedy many-to-many match between two token slices."""
    if not hypothesis:
        return []
    if not reference:
        return [None] * len(hypothesis)

    if len(hypothesis) == len(reference):
        return list(reference)

    result: list[str | None] = [None] * len(hypothesis)
    used_ref: set[int] = set()

    for hi, hyp_token in enumerate(hypothesis):
        best_j = -1
        best_sim = -1.0
        for rj, ref_token in enumerate(reference):
            if rj in used_ref:
                continue
            sim = fuzz.ratio(hyp_token, ref_token)
            if sim > best_sim:
                best_sim = sim
                best_j = rj
        if best_j >= 0 and best_sim >= 40:
            result[hi] = reference[best_j]
            used_ref.add(best_j)

    return result
