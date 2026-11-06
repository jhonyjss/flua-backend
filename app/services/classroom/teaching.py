"""Server-owned teaching material for the spoken reply."""

from pathlib import Path

from app.core.config import get_settings

GREETINGS = (
    Path(__file__).parents[1] / "prompts/flua_teaching_greetings.md"
).read_text(encoding="utf-8")


def skill_for_lesson(lesson_id: str) -> str:
    if get_settings().classroom_teaching_pilot_enabled and lesson_id == "fund-u1-l1":
        return GREETINGS
    return ""
