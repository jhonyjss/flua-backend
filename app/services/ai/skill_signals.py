"""Deterministic skill signals for the hybrid lesson evaluation.

These produce objective 0–100 scores for each skill (Gramática, Vocabulário,
Pronúncia, Conversação, Compreensão) computed *purely* from real lesson data —
no LLM, no I/O. They are the auditable half of the hybrid score; the LLM judge
refines them afterwards. Keep this module pure and side-effect free so it stays
fast and unit-testable (pytest, no fixtures).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_WORD_RE = re.compile(r"[a-zA-Z']+")

# Common English function words excluded from lexical-variety so "the/a/is" do
# not inflate vocabulary breadth.
_STOPWORDS: frozenset[str] = frozenset(
    """a an the and or but so to of in on at for with from by is am are was were be
    been being do does did have has had i you he she it we they me him her them my
    your his their our this that these those not no yes ok okay well just very
    really too also then than as if when what which who how why where""".split()
)

# Phrases that signal the student did not understand and asked for help/repeat.
_CONFUSION_MARKERS: tuple[str, ...] = (
    "repeat",
    "again",
    "sorry",
    "pardon",
    "what?",
    "don't understand",
    "do not understand",
    "didn't understand",
    "i don't know",
    "nao entendi",
    "não entendi",
    "de novo",
    "repete",
    "como assim",
    "como?",
)

_HELP_MARKERS: tuple[str, ...] = (
    "preciso de ajuda",
    "need help",
    "help me",
    "ajuda",
)


@dataclass(frozen=True)
class Turn:
    """A finalized conversation turn. role is 'student' or 'tutor'."""

    role: str
    text: str


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def _norm(text: str) -> str:
    """Lowercase + accent-fold for robust substring matching (PT/EN)."""
    return _strip_accents(text or "").lower()


def _tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD_RE.finditer(text or "")]


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _coerce_turns(turns: list[Turn] | list[dict]) -> list[Turn]:
    out: list[Turn] = []
    for t in turns or []:
        if isinstance(t, Turn):
            out.append(t)
        elif isinstance(t, dict):
            out.append(Turn(role=str(t.get("role", "")), text=str(t.get("text", ""))))
    return out


# ── Per-skill signals ──────────────────────────────────────────────────────


def vocabulary_signal(student_text: str, target_vocab: list[str]) -> int:
    """0.6 · cobertura do vocabulário-alvo + 0.4 · variedade lexical."""
    norm_text = _norm(student_text)
    content_words = [t for t in _tokens(student_text) if t not in _STOPWORDS]
    # Up to 25 distinct content words → full variety credit.
    variety = min(1.0, len(set(content_words)) / 25.0)

    targets = [w for w in (target_vocab or []) if w.strip()]
    if not targets:
        return _clamp(100 * variety)

    covered = sum(1 for w in targets if _norm(w) in norm_text)
    coverage = covered / len(targets)
    return _clamp(100 * (0.6 * coverage + 0.4 * variety))


def grammar_signal(
    corrections_received: int,
    student_turn_count: int,
    phrase_scores: list[int] | None = None,
) -> int:
    """Fewer corrections-per-turn → higher; blended with guided-phrase scores."""
    turns = max(1, student_turn_count)
    corrections_per_turn = max(0, corrections_received) / turns
    # 0 corrections → 100; ~1.5 corrections/turn → ~40.
    corrections_score = 100 - min(60, corrections_per_turn * 40)

    if phrase_scores:
        return _clamp(0.5 * corrections_score + 0.5 * _mean(phrase_scores))
    return _clamp(corrections_score)


def pronunciation_signal(
    phrase_scores: list[int] | None = None,
    stt_confidence: float | None = None,
) -> tuple[int, bool]:
    """Returns (score, is_proxy).

    Phase 2: average word-level STT confidence (strong signal). Phase 1 (now):
    proxy from guided-phrase recognition scores → flagged `is_proxy=True` so the
    caller lowers overall confidence for this skill.
    """
    if stt_confidence is not None:
        return _clamp(stt_confidence * 100), False
    if phrase_scores:
        return _clamp(_mean(phrase_scores)), True
    return 50, True


def conversation_signal(
    student_turns: list[Turn],
    help_requests: int,
    completion_rate: float,
) -> int:
    """Functional fluency from turn volume, depth, initiative and completion."""
    n = len(student_turns)
    if n == 0:
        return 0

    lengths = [len(_tokens(t.text)) for t in student_turns]
    avg_len = _mean(lengths)
    volume = min(1.0, n / 8.0)          # 8+ student turns → full
    depth = min(1.0, avg_len / 8.0)     # avg 8+ words/turn → full
    initiative = sum(1 for length in lengths if length > 3) / n
    help_penalty = min(0.2, max(0, help_requests) * 0.05)

    base = 0.4 * volume + 0.35 * depth + 0.25 * initiative
    base = max(0.0, base - help_penalty)
    completion = max(0.0, min(1.0, completion_rate))
    return _clamp(100 * (0.7 * base + 0.3 * completion))


def comprehension_signal(student_turns: list[Turn]) -> int:
    """Did the student respond without asking for repetition?"""
    n = len(student_turns)
    if n == 0:
        return 50
    confused = sum(
        1
        for t in student_turns
        if any(marker in _norm(t.text) for marker in _CONFUSION_MARKERS)
    )
    ratio = confused / n
    return _clamp(100 * (1 - min(1.0, ratio * 1.5)))


def confidence_for(student_turn_count: int) -> float:
    """Low confidence with few turns; full at ~12 student turns."""
    return round(min(1.0, max(0, student_turn_count) / 12.0), 2)


def _count_markers(text: str, markers: tuple[str, ...]) -> int:
    norm = _norm(text)
    return sum(1 for m in markers if _norm(m) in norm)


def compute_deterministic(
    turns: list[Turn] | list[dict],
    target_vocab: list[str] | None = None,
    corrections_received: int = 0,
    completion_rate: float = 0.0,
    phrase_scores: list[int] | None = None,
    stt_confidence: float | None = None,
) -> dict:
    """Assemble the deterministic 0–100 score per skill plus a confidence.

    `completion_rate` is 0–1 (objectives completed / total).
    """
    all_turns = _coerce_turns(turns)
    student_turns = [t for t in all_turns if t.role == "student"]
    student_text = " ".join(t.text for t in student_turns)
    help_requests = sum(_count_markers(t.text, _HELP_MARKERS) for t in student_turns)

    pronunciation, pron_is_proxy = pronunciation_signal(phrase_scores, stt_confidence)

    return {
        "grammar": grammar_signal(corrections_received, len(student_turns), phrase_scores),
        "vocabulary": vocabulary_signal(student_text, target_vocab or []),
        "pronunciation": pronunciation,
        "conversation": conversation_signal(student_turns, help_requests, completion_rate),
        "comprehension": comprehension_signal(student_turns),
        "confidence": confidence_for(len(student_turns)),
        "turns_count": len(student_turns),
        "pronunciation_is_proxy": pron_is_proxy,
    }
