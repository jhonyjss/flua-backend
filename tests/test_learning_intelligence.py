"""Unit tests for the learning-intelligence cores (spaced repetition + recos)."""

from datetime import timedelta

from app.services.ai.recommendation import recommend_next
from app.services.ai.spaced_repetition import (
    SrsState,
    calculate_next_review,
    review,
    status_for,
)


# ── Spaced repetition (SM-2-lite) ────────────────────────────────────────


def test_first_successful_review_schedules_one_day():
    out = review(SrsState(), quality=4)
    assert out.reps == 1
    assert out.interval_days == 1
    assert out.confidence > 0.30
    assert out.status in ("learning", "reviewing")


def test_intervals_grow_with_consecutive_passes():
    s = SrsState()
    s = review(s, 5)  # rep1 → 1d
    assert s.interval_days == 1
    s = review(s, 5)  # rep2 → 6d
    assert s.interval_days == 6
    s = review(s, 5)  # rep3 → 6 * ease (~>6)
    assert s.interval_days > 6
    assert s.reps == 3


def test_failure_resets_and_counts_lapse():
    s = review(SrsState(), 5)
    s = review(s, 5)
    failed = review(s, 1)  # quality < 3 → lapse
    assert failed.reps == 0
    assert failed.interval_days == 1
    assert failed.lapses == 1
    assert failed.confidence < s.confidence
    assert failed.status == "learning"


def test_reaches_mastered_after_strong_streak():
    s = SrsState()
    for _ in range(6):
        s = review(s, 5)
    assert s.status == "mastered"
    assert s.confidence >= 0.85
    assert s.ease >= 1.3


def test_status_for_thresholds():
    assert status_for(0.1, 0, False) == "new"
    assert status_for(0.4, 1, False) == "learning"
    assert status_for(0.6, 2, False) == "reviewing"
    assert status_for(0.9, 4, False) == "mastered"
    assert status_for(0.9, 4, True) == "learning"  # a lapse always demotes


def test_calculate_next_review_heuristic():
    assert calculate_next_review(0.3, 0) == timedelta(days=1)
    assert calculate_next_review(0.6, 3) == timedelta(days=2)  # mistakes dominate
    assert calculate_next_review(0.6, 0) == timedelta(days=3)
    assert calculate_next_review(0.9, 0) == timedelta(days=7)


# ── Recommendation engine ────────────────────────────────────────────────


def test_recommends_error_drill_first():
    out = recommend_next(
        top_errors=[{"error_text": "based off", "correction": "based on", "category": "preposition", "count": 5}],
        due_vocab=[{"term": "make an effort"}],
        lesson_in_progress={"lesson_id": "l1", "percentage": 40},
    )
    assert out["next_activity"] == "practice_errors"
    assert "based on" in out["items"]


def test_recommends_vocabulary_review_when_due_and_no_big_errors():
    out = recommend_next(
        top_errors=[{"error_text": "a", "correction": "an", "count": 1}],  # below threshold
        due_vocab=[{"term": "make an effort"}, {"term": "do homework"}],
        minutes_available=10,
    )
    assert out["next_activity"] == "review_vocabulary"
    assert "make an effort" in out["items"]


def test_short_session_caps_review_items():
    due = [{"term": f"w{i}"} for i in range(8)]
    out = recommend_next(due_vocab=due, minutes_available=5)
    assert len(out["items"]) == 3  # capped for a short session


def test_continues_lesson_when_no_errors_or_due_vocab():
    out = recommend_next(lesson_in_progress={"lesson_id": "l9", "percentage": 60})
    assert out["next_activity"] == "continue_lesson"
    assert out["items"] == ["l9"]


def test_falls_back_to_weakness_then_free_conversation():
    out_w = recommend_next(profile={"level": "B1", "weaknesses": ["phrasal_verbs", "prepositions"]})
    assert out_w["next_activity"] == "practice_weakness"
    assert out_w["items"] == ["phrasal_verbs", "prepositions"]

    out_free = recommend_next(profile={"level": "B1"})
    assert out_free["next_activity"] == "free_conversation"
