import json
from functools import cache
from pathlib import Path

from fastapi import HTTPException

from app.schemas.realtime import GuidedPlan


@cache
def catalog(web=False):
    filename = "classroom_web_lessons.json" if web else "classroom_lessons.json"
    return json.loads((Path(__file__).parents[2] / "data" / filename).read_text())


def lesson(lesson_id: str, version: str) -> dict:
    data = catalog(version.startswith("web-"))
    if version != data["contentVersion"]:
        raise HTTPException(
            409,
            {"code": "content_version", "message": "Atualize o app para continuar."},
        )
    plan = data["lessons"].get(lesson_id)
    if not plan:
        raise HTTPException(404, {"code": "lesson_not_found"})
    return GuidedPlan.model_validate(plan).model_dump()
