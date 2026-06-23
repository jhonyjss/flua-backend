"""Next-best-activity recommendation engine.

Pure & deterministic: given a snapshot of the student (profile, top recurring
errors, vocabulary due for review, current lesson progress, time available) it
returns the next activity plus a human "reason". The reason is rule-generated
(auditable), NOT an LLM hallucination.
"""

from __future__ import annotations

# An error seen this many times is worth a dedicated drill.
ERROR_DRILL_THRESHOLD = 3


def recommend_next(
    profile: dict | None = None,
    top_errors: list[dict] | None = None,
    due_vocab: list[dict] | None = None,
    lesson_in_progress: dict | None = None,
    minutes_available: int = 10,
) -> dict:
    profile = profile or {}
    top_errors = top_errors or []
    due_vocab = due_vocab or []

    # 1) Recurring error that crossed the drill threshold → fix it first.
    drill = next((e for e in top_errors if int(e.get("count", 0)) >= ERROR_DRILL_THRESHOLD), None)
    if drill:
        wrong = drill.get("error_text", "")
        right = drill.get("correction", "")
        return {
            "next_activity": "practice_errors",
            "reason": f"Você errou \"{wrong}\" {drill.get('count')} vezes — vamos fixar \"{right}\".",
            "items": [e.get("correction", "") for e in top_errors[:4] if e.get("correction")],
        }

    # 2) Vocabulary due for review (don't let the SRS queue pile up).
    if due_vocab:
        # Short sessions → fewer items.
        cap = 5 if minutes_available >= 10 else 3
        terms = [v.get("term", "") for v in due_vocab[:cap] if v.get("term")]
        return {
            "next_activity": "review_vocabulary",
            "reason": f"{len(due_vocab)} palavra(s)/expressão(ões) estão na hora de revisar.",
            "items": terms,
        }

    # 3) Finish the lesson in progress.
    if lesson_in_progress and int(lesson_in_progress.get("percentage", 0)) < 100:
        lid = lesson_in_progress.get("lesson_id", "")
        return {
            "next_activity": "continue_lesson",
            "reason": "Você tem uma aula em andamento — vamos terminá-la.",
            "items": [lid] if lid else [],
        }

    # 4) Target the student's known weaknesses / goal.
    weaknesses = [w for w in (profile.get("weaknesses") or []) if w]
    if weaknesses:
        return {
            "next_activity": "practice_weakness",
            "reason": f"Focar nos seus pontos de atenção: {', '.join(weaknesses[:3])}.",
            "items": weaknesses[:3],
        }

    # 5) Nothing pending → free, level-appropriate conversation.
    level = profile.get("level", "A1")
    return {
        "next_activity": "free_conversation",
        "reason": f"Tudo em dia! Que tal uma conversa livre no seu nível ({level})?",
        "items": [],
    }
