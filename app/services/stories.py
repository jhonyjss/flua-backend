"""Stories (graded reading + vocabulary + quiz), ported from the site's Nitro routes
(flueai server/api/stories/* and server/utils/stories/{access,quota,scoring,streak}.ts).

Rules kept from the site:
- Free accounts start 3 new stories per UTC week (Monday 00:00 UTC); reopening a started story never
  counts. A paid plan or the in-app trial (profiles.app_trial_ends_at in the future) reads unlimited.
- XP for a story = 10 + 2 x correct answers, scored here from story_questions, paid once.

What changed on the way: "paid" comes from get_subscription (Stripe merged with the app stores
through RevenueCat), so a plan bought in the app counts; and XP and the streak go through the
shared progress core (award_web_xp / record_web_practice), so the ledger, "Foco de hoje" and the
São Paulo streak day are the same as everywhere else.
"""
import re
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from app.schemas.stories import QUESTIONS_PER_STORY
from app.services import learning
from app.services import supabase_admin as db
from app.services.user_data import get_subscription

FREE_STORIES_PER_WEEK = 3
STORY_XP_BASE = 10
STORY_XP_PER_CORRECT = 2
PAID_STATUSES = {"active", "trialing"}

QUOTA_MESSAGE = "Você atingiu o limite de 3 histórias nesta semana. Assine para leitura ilimitada."

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

LIST_COLUMNS = "id,title,cefr_level,topic,word_count,created_at"
STORY_COLUMNS = "id,title,cefr_level,topic,passage,word_count,audio_url,audio_voice,audio_alignment"
PROGRESS_COLUMNS = ("step", "quiz_score", "xp_earned", "completed_at")
EXPRESSION_COLUMNS = (
    "id,expression,occurrence_index,part_of_speech,phonetic,definition_en,definition_pt,sort_order,audio_url"
)
QUESTION_COLUMNS = "id,question,options,correct_index,explanation,sort_order"


# ── Pure rules ────────────────────────────────────────────────────────

def week_start_utc(now: datetime) -> datetime:
    """Monday 00:00 UTC of the week `now` falls in."""
    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def compute_story_quota(is_paid: bool, started_this_week: int) -> dict:
    if is_paid:
        return {"limit": None, "used": started_this_week, "remaining": None, "allowed": True}
    remaining = max(0, FREE_STORIES_PER_WEEK - started_this_week)
    return {"limit": FREE_STORIES_PER_WEEK, "used": started_this_week, "remaining": remaining, "allowed": remaining > 0}


def score_quiz(answers: list[int], correct_indexes: list[int]) -> int:
    if len(answers) != len(correct_indexes):
        return 0
    return sum(1 for answer, correct in zip(answers, correct_indexes, strict=True) if answer == correct)


def story_xp(correct_count: int) -> int:
    if correct_count < 0:
        return STORY_XP_BASE
    return STORY_XP_BASE + STORY_XP_PER_CORRECT * correct_count


def is_paid_plan(status: str | None, plan_level: str | None) -> bool:
    """Active or trialing on a plan other than free (the site's hasActiveSubscription)."""
    return (status or "free") in PAID_STATUSES and (plan_level or "free").lower() != "free"


def trial_active(trial_ends_at: str | None, now: datetime) -> bool:
    if not trial_ends_at:
        return False
    try:
        ends = datetime.fromisoformat(trial_ends_at)
    except ValueError:
        return False
    if ends.tzinfo is None:
        ends = ends.replace(tzinfo=UTC)
    return now < ends


def require_story_id(value: str) -> str:
    if not _UUID.match(value or ""):
        raise HTTPException(400, "ID inválido.")
    return value


def _progress_view(row: dict) -> dict:
    return {col: row.get(col) for col in PROGRESS_COLUMNS}


# ── Context (quota + stats) ───────────────────────────────────────────

async def user_context(user_id: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    week_start = week_start_utc(now).isoformat().replace("+00:00", "Z")
    profile = await db.select_one("profiles", {"id": user_id}) or {}
    streak = await db.select_one("user_streaks", {"user_id": user_id}) or {}
    started = await db.select_many(
        "user_story_progress", {"user_id": user_id}, select="id", op_filters={"started_at": f"gte.{week_start}"},
    )
    subscription = await get_subscription(user_id)
    is_paid = is_paid_plan(subscription.status, subscription.planLevel) or trial_active(
        profile.get("app_trial_ends_at"), now,
    )
    return {
        "isPaid": is_paid,
        "quota": compute_story_quota(is_paid, len(started)),
        "stats": {"xp": profile.get("xp") or 0, "streak": streak.get("current_streak") or 0},
    }


# ── Endpoints' logic ──────────────────────────────────────────────────

async def list_stories(user_id: str) -> dict:
    stories = await db.select_many(
        "stories", {"status": "published"}, select=LIST_COLUMNS, order="cefr_level.asc,created_at.desc",
    )
    progress_rows = await db.select_many(
        "user_story_progress", {"user_id": user_id}, select="story_id," + ",".join(PROGRESS_COLUMNS),
    )
    context = await user_context(user_id)
    by_story = {row["story_id"]: row for row in progress_rows}
    return {
        "success": True,
        "stories": [
            {**story, "progress": _progress_view(by_story[story["id"]]) if story["id"] in by_story else None}
            for story in stories
        ],
        "quota": context["quota"],
        "stats": context["stats"],
    }


async def _find_progress(user_id: str, story_id: str, columns: str) -> dict | None:
    rows = await db.select_many(
        "user_story_progress", {"user_id": user_id, "story_id": story_id}, select=columns, limit=1,
    )
    return rows[0] if rows else None


async def open_story(user_id: str, story_id: str) -> dict:
    found = await db.select_many(
        "stories", {"id": story_id, "status": "published"}, select=STORY_COLUMNS, limit=1,
    )
    if not found:
        raise HTTPException(404, "História não encontrada.")
    progress = await _find_progress(user_id, story_id, ",".join(PROGRESS_COLUMNS))
    context = await user_context(user_id)
    quota = context["quota"]

    if progress is None:
        if not quota["allowed"]:
            raise HTTPException(
                status_code=403,
                detail={"code": "QUOTA_EXCEEDED", "reason": "QUOTA_EXCEEDED", "message": QUOTA_MESSAGE},
            )
        try:
            created = await db.insert("user_story_progress", {"user_id": user_id, "story_id": story_id, "step": "reading"})
        except HTTPException:
            # A double tap: the other request created it first (unique user_id, story_id); not a new start.
            created = await _find_progress(user_id, story_id, ",".join(PROGRESS_COLUMNS))
            if created is None:
                raise HTTPException(500, "Falha ao iniciar a história.") from None
        else:
            if created is None:
                raise HTTPException(500, "Falha ao iniciar a história.")
            quota["used"] += 1
            if quota["remaining"] is not None:
                quota["remaining"] = max(0, quota["remaining"] - 1)
        progress = created

    expressions = await db.select_many(
        "story_expressions", {"story_id": story_id}, select=EXPRESSION_COLUMNS, order="sort_order.asc",
    )
    questions = await db.select_many(
        "story_questions", {"story_id": story_id}, select=QUESTION_COLUMNS, order="sort_order.asc",
    )
    return {
        "success": True,
        "story": found[0],
        "expressions": expressions,
        "questions": questions,
        "progress": _progress_view(progress),
        "quota": quota,
        "stats": context["stats"],
    }


async def save_step(user_id: str, story_id: str, step: str) -> dict:
    existing = await _find_progress(user_id, story_id, "step,completed_at")
    if existing is None:
        raise HTTPException(404, "Progresso não encontrado. Abra a história primeiro.")
    if existing.get("completed_at"):
        return {"success": True, "step": "done"}
    await db.update("user_story_progress", {"user_id": user_id, "story_id": story_id}, {"step": step})
    return {"success": True, "step": step}


async def _current_streak(user_id: str) -> int:
    row = await db.select_one("user_streaks", {"user_id": user_id})
    return (row or {}).get("current_streak") or 0


async def complete_story(user_id: str, story_id: str, answers: list[int]) -> dict:
    progress = await _find_progress(user_id, story_id, "id," + ",".join(PROGRESS_COLUMNS))
    if progress is None:
        raise HTTPException(404, "Progresso não encontrado. Abra a história primeiro.")
    questions = await db.select_many(
        "story_questions", {"story_id": story_id}, select="correct_index,sort_order", order="sort_order.asc",
    )
    if len(questions) != QUESTIONS_PER_STORY:
        raise HTTPException(500, "Falha ao corrigir o quiz.")
    correct_count = score_quiz(answers, [q["correct_index"] for q in questions])

    def already(quiz_score: int | None, streak: int) -> dict:
        return {
            "success": True, "alreadyCompleted": True, "correctCount": correct_count, "total": QUESTIONS_PER_STORY,
            "xpEarned": 0, "quizScore": quiz_score, "streak": streak,
        }

    if progress.get("completed_at"):
        return already(progress.get("quiz_score"), await _current_streak(user_id))

    xp_earned = story_xp(correct_count)
    # Claim the completion first, only while it is still open: of two concurrent calls exactly one
    # gets the row back, and only that one pays XP and advances the streak.
    claimed = await db.update_returning(
        "user_story_progress",
        {"id": str(progress["id"])},
        {"step": "done", "quiz_score": correct_count, "xp_earned": xp_earned, "completed_at": datetime.now(UTC).isoformat()},
        op_filters={"completed_at": "is.null"},
    )
    if not claimed:
        winner = await _find_progress(user_id, story_id, "quiz_score")
        return already((winner or {}).get("quiz_score"), await _current_streak(user_id))

    await learning.award_xp(user_id, xp_earned)
    practice = await learning.record_practice(user_id, 0, False)
    return {
        "success": True, "alreadyCompleted": False, "correctCount": correct_count, "total": QUESTIONS_PER_STORY,
        "xpEarned": xp_earned, "quizScore": correct_count, "streak": int(practice.get("streak") or 0),
    }
