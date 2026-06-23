"""English dictionary loading, caching, and fuzzy candidate generation."""
from __future__ import annotations

import logging
import math
from functools import lru_cache

from rapidfuzz import fuzz, process
from symspellpy import SymSpell, Verbosity
from wordfreq import top_n_list, word_frequency

from speech.config import SpeechPipelineConfig

logger = logging.getLogger(__name__)


class EnglishDictionary:
    """Cached vocabulary with SymSpell + RapidFuzz candidate lookup."""

    def __init__(self, config: SpeechPipelineConfig | None = None) -> None:
        self.config = config or SpeechPipelineConfig()
        self._words: list[str] = []
        self._word_set: set[str] = set()
        self._freq_cache: dict[str, float] = {}
        self._sym_spell: SymSpell | None = None
        self._loaded = False

    def load_from_words(self, words: list[str]) -> None:
        """Load a custom in-memory dictionary (used in tests or lesson-scoped vocab)."""
        self._words = list(words)
        self._word_set = set(words)

        sym = SymSpell(
            max_dictionary_edit_distance=self.config.max_edit_distance,
            prefix_length=7,
        )
        for word in words:
            freq = word_frequency(word, "en")
            sym.create_dictionary_entry(word, max(1, int(freq * 1_000_000)))

        self._sym_spell = sym
        self._loaded = True
        logger.info("Custom dictionary ready: %d entries", len(self._words))

    def load(self) -> None:
        if self._loaded:
            return

        size = self.config.dictionary_size
        logger.info("Loading English dictionary (top %d words from wordfreq)", size)
        words = top_n_list("en", size)
        self._words = words
        self._word_set = set(words)

        sym = SymSpell(
            max_dictionary_edit_distance=self.config.max_edit_distance,
            prefix_length=7,
        )
        for word in words:
            freq = word_frequency(word, "en")
            # SymSpell expects integer frequency; scale log-probability to int.
            sym.create_dictionary_entry(word, max(1, int(freq * 1_000_000)))

        self._sym_spell = sym
        self._loaded = True
        logger.info("Dictionary ready: %d entries", len(self._words))

    @property
    def words(self) -> list[str]:
        self.load()
        return self._words

    @property
    def word_set(self) -> set[str]:
        self.load()
        return self._word_set

    def frequency(self, word: str) -> float:
        self.load()
        w = word.lower()
        if w not in self._freq_cache:
            self._freq_cache[w] = word_frequency(w, "en")
        return self._freq_cache[w]

    def frequency_score(self, word: str) -> float:
        """Map wordfreq probability to 0–1 (log-scaled)."""
        freq = self.frequency(word)
        if freq <= 0:
            return 0.0
        # wordfreq top words are ~1e-2; rare words ~1e-8.
        return min(1.0, (math.log10(freq) + 8.0) / 8.0)

    def _sym_suggestions(self, word: str) -> list[str]:
        self.load()
        assert self._sym_spell is not None
        suggestions = self._sym_spell.lookup(
            word,
            Verbosity.CLOSEST,
            max_edit_distance=self.config.max_edit_distance,
        )
        return [s.term for s in suggestions[: self.config.max_candidates_per_token]]

    def get_candidates(self, word: str) -> list[str]:
        """Return ranked candidate corrections for a single token."""
        self.load()
        token = word.lower().strip()
        if not token:
            return []

        if token in self._word_set:
            return [token]

        pool: dict[str, float] = {}

        for suggestion in self._sym_suggestions(token):
            pool[suggestion] = max(pool.get(suggestion, 0.0), 0.85)

        fuzzy_hits = process.extract(
            token,
            self._words,
            scorer=fuzz.WRatio,
            limit=self.config.max_candidates_per_token,
        )
        for match, score, _ in fuzzy_hits:
            if score >= self.config.min_dictionary_fuzzy_score:
                pool[match] = max(pool.get(match, 0.0), score / 100.0)

        if not pool:
            return [token]

        ranked = sorted(
            pool.keys(),
            key=lambda w: (
                pool[w] * self.config.fuzzy_weight
                + self.frequency_score(w) * self.config.frequency_weight
            ),
            reverse=True,
        )
        return ranked[: self.config.max_candidates_per_token]


@lru_cache(maxsize=4)
def get_dictionary(
    dictionary_size: int = 200_000,
    max_edit_distance: int = 2,
) -> EnglishDictionary:
    """Process-wide cached dictionary singleton."""
    cfg = SpeechPipelineConfig(
        dictionary_size=dictionary_size,
        max_edit_distance=max_edit_distance,
    )
    dictionary = EnglishDictionary(cfg)
    dictionary.load()
    return dictionary
