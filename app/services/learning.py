"""Learning data + business logic (ported from useLessonProgress / useStreaks).

Multi-step writes (start/complete lesson, save topic, record practice, award XP)
run server-side and atomically here, so the client just POSTs intent. Pure
helpers (xp/level math, streak transition, weekly activity) are unit-tested
without network.
"""
import json
from datetime import date, datetime, timedelta, timezone

from app.services import supabase_admin as db

XP_PER_LEVEL = 200
STREAK_MILESTONES = [(3, "streak_3"), (7, "streak_7"), (14, "streak_14"), (30, "streak_30")]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return date.today().isoformat()


def normalize_topic_ids(value) -> list[str]:
    """JSONB that may arrive as a string or list → list[str]."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


# ── Pure helpers ──────────────────────────────────────────────────────

def compute_level(xp: int) -> int:
    return xp // XP_PER_LEVEL + 1


def apply_xp(current_xp: int, current_level: int, amount: int) -> dict:
    new_xp = current_xp + amount
    new_level = compute_level(new_xp)
    return {"newXp": new_xp, "newLevel": new_level, "leveledUp": new_level > current_level}


def compute_streak_transition(streak_row: dict, today: str) -> dict:
    """Pure streak math (mirrors useStreaks.recordPractice)."""
    last = streak_row.get("last_practice_date")
    is_new_day = last != today
    new_streak = streak_row.get("current_streak") or 0
    start = streak_row.get("streak_start_date")

    if is_new_day:
        yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
        if last == yesterday:
            new_streak += 1
        else:
            new_streak = 1
            start = today

    longest = max(streak_row.get("longest_streak") or 0, new_streak)

    weekly = list(streak_row.get("weekly_activity") or []) if isinstance(streak_row.get("weekly_activity"), list) else []
    if is_new_day:
        weekly.append(today)
        weekly = sorted(set(weekly))[-7:]

    return {
        "isNewDay": is_new_day,
        "current_streak": new_streak,
        "longest_streak": longest,
        "streak_start_date": start,
        "weekly_activity": weekly,
    }


def streak_achievements(current_streak: int, already_unlocked: list[str]) -> list[str]:
    return [
        aid for threshold, aid in STREAK_MILESTONES
        if current_streak >= threshold and aid not in already_unlocked
    ]


# ── Lesson progress ───────────────────────────────────────────────────

async def get_lesson_progress(user_id: str, lesson_id: str) -> dict | None:
    rows = await db.select_many("lesson_progress", {"user_id": user_id, "lesson_id": lesson_id}, limit=1)
    return rows[0] if rows else None


async def list_progress(user_id: str) -> list[dict]:
    return await db.select_many("lesson_progress", {"user_id": user_id}, order="updated_at.desc")


async def completed_lesson_ids(user_id: str) -> list[str]:
    rows = await db.select_many(
        "lesson_progress", {"user_id": user_id, "status": "completed"}, select="lesson_id",
    )
    return [r["lesson_id"] for r in rows if r.get("lesson_id")]


async def unlocked_lesson_ids(user_id: str) -> list[str]:
    rows = await db.select_many(
        "lesson_progress", {"user_id": user_id, "status": "unlocked"}, select="lesson_id",
    )
    return [r["lesson_id"] for r in rows if r.get("lesson_id")]


async def in_progress_lessons(user_id: str) -> dict[str, int]:
    rows = await db.select_many(
        "lesson_progress", {"user_id": user_id, "status": "in_progress"},
        select="lesson_id,completed_topic_ids",
    )
    result: dict[str, int] = {}
    for row in rows:
        topics = normalize_topic_ids(row.get("completed_topic_ids"))
        if topics:
            result[row["lesson_id"]] = len(topics)
    return result


async def completed_topic_ids(user_id: str, lesson_id: str) -> list[str]:
    progress = await get_lesson_progress(user_id, lesson_id)
    return normalize_topic_ids(progress.get("completed_topic_ids")) if progress else []


async def start_lesson(user_id: str, lesson_id: str, session_id: str) -> None:
    existing = await get_lesson_progress(user_id, lesson_id)
    if existing:
        new_status = "completed" if existing.get("status") == "completed" else "in_progress"
        await db.update("lesson_progress", {"id": str(existing["id"])}, {
            "status": new_status,
            "started_at": existing.get("started_at") or _now_iso(),
            "attempts": (existing.get("attempts") or 0) + 1,
            "last_session_id": session_id,
        })
    else:
        await db.insert("lesson_progress", {
            "user_id": user_id,
            "lesson_id": lesson_id,
            "status": "in_progress",
            "unlocked_by": "previous_lesson",
            "started_at": _now_iso(),
            "attempts": 1,
            "last_session_id": session_id,
        })


async def complete_lesson(user_id: str, lesson_id: str, stats: dict) -> None:
    existing = await get_lesson_progress(user_id, lesson_id)
    score = round((stats["rating"] / 5) * 100)
    if existing:
        topic_ids = normalize_topic_ids(existing.get("completed_topic_ids"))
        await db.update("lesson_progress", {"id": str(existing["id"])}, {
            "status": "completed",
            "completed_at": _now_iso(),
            "score": score,
            "topics_completed": max(stats["topicsCompleted"], len(topic_ids)),
            "completed_topic_ids": topic_ids,
            "time_spent_seconds": (existing.get("time_spent_seconds") or 0) + stats["timeSpentSeconds"],
            "best_rating": max(existing.get("best_rating") or 0, stats["rating"]),
            "last_session_id": stats["sessionId"],
        })
    else:
        await db.insert("lesson_progress", {
            "user_id": user_id,
            "lesson_id": lesson_id,
            "status": "completed",
            "unlocked_by": "previous_lesson",
            "started_at": _now_iso(),
            "completed_at": _now_iso(),
            "score": score,
            "topics_completed": stats["topicsCompleted"],
            "completed_topic_ids": [],
            "time_spent_seconds": stats["timeSpentSeconds"],
            "best_rating": stats["rating"],
            "attempts": 1,
            "last_session_id": stats["sessionId"],
        })


async def save_topic_completion(user_id: str, lesson_id: str, topic_id: str) -> None:
    existing = await get_lesson_progress(user_id, lesson_id)
    now = _now_iso()
    if existing:
        topic_ids = normalize_topic_ids(existing.get("completed_topic_ids"))
        if topic_id in topic_ids:
            return
        next_ids = [*topic_ids, topic_id]
        await db.update("lesson_progress", {"id": str(existing["id"])}, {
            "status": "completed" if existing.get("status") == "completed" else "in_progress",
            "started_at": existing.get("started_at") or now,
            "topics_completed": len(next_ids),
            "completed_topic_ids": next_ids,
        })
    else:
        await db.insert("lesson_progress", {
            "user_id": user_id,
            "lesson_id": lesson_id,
            "status": "in_progress",
            "unlocked_by": "previous_lesson",
            "started_at": now,
            "attempts": 1,
            "topics_completed": 1,
            "completed_topic_ids": [topic_id],
        })


async def unlock_lesson(user_id: str, lesson_id: str, unlocked_by: str) -> None:
    existing = await get_lesson_progress(user_id, lesson_id)
    if existing:
        if existing.get("status") in ("in_progress", "completed"):
            return
        await db.update("lesson_progress", {"id": str(existing["id"])}, {"status": "unlocked"})
    else:
        await db.insert("lesson_progress", {
            "user_id": user_id, "lesson_id": lesson_id, "status": "unlocked", "unlocked_by": unlocked_by,
        })


# ── Class sessions ────────────────────────────────────────────────────

async def save_class_session(user_id: str, session: dict) -> None:
    existing = await db.select_many(
        "class_sessions", {"user_id": user_id, "session_id": session["session_id"]}, select="id", limit=1,
    )
    payload = {**session, "status": session.get("status") or "completed"}
    if existing:
        await db.update("class_sessions", {"id": str(existing[0]["id"])}, payload)
    else:
        await db.insert("class_sessions", {**payload, "user_id": user_id})


async def recent_sessions(user_id: str, limit: int) -> list[dict]:
    return await db.select_many(
        "class_sessions", {"user_id": user_id}, order="started_at.desc", limit=limit,
    )


# ── XP / level ────────────────────────────────────────────────────────

async def award_xp(user_id: str, amount: int) -> dict | None:
    profile = await db.select_one("profiles", {"id": user_id})
    if not profile:
        return None
    result = apply_xp(profile.get("xp") or 0, profile.get("level") or 1, amount)
    await db.update("profiles", {"id": user_id}, {"xp": result["newXp"], "level": result["newLevel"]})
    return result


# ── Streaks / achievements ────────────────────────────────────────────

async def get_or_create_streak(user_id: str) -> dict:
    row = await db.select_one("user_streaks", {"user_id": user_id})
    if row:
        return row
    created = await db.insert("user_streaks", {"user_id": user_id})
    return created or {"user_id": user_id, "current_streak": 0, "longest_streak": 0,
                       "total_practice_days": 0, "weekly_activity": []}


async def unlocked_achievement_ids(user_id: str) -> list[str]:
    rows = await db.select_many("user_achievements", {"user_id": user_id}, select="achievement_id")
    return [r["achievement_id"] for r in rows if r.get("achievement_id")]


async def unlock_achievements(user_id: str, achievement_ids: list[str]) -> None:
    for aid in achievement_ids:
        await db.upsert(
            "user_achievements",
            {"user_id": user_id, "achievement_id": aid, "metadata": {}},
            on_conflict="user_id,achievement_id",
        )


async def record_practice(user_id: str, time_seconds: int, lesson_completed: bool) -> dict:
    streak_row = await get_or_create_streak(user_id)
    transition = compute_streak_transition(streak_row, _today())

    await db.update("user_streaks", {"user_id": user_id}, {
        "current_streak": transition["current_streak"],
        "longest_streak": transition["longest_streak"],
        "last_practice_date": _today(),
        "streak_start_date": transition["streak_start_date"],
        "weekly_activity": transition["weekly_activity"],
        "total_practice_days": (streak_row.get("total_practice_days") or 0) + (1 if transition["isNewDay"] else 0),
        "total_lessons_completed": (streak_row.get("total_lessons_completed") or 0) + (1 if lesson_completed else 0),
        "total_time_seconds": (streak_row.get("total_time_seconds") or 0) + time_seconds,
    })

    already = await unlocked_achievement_ids(user_id)
    to_unlock = streak_achievements(transition["current_streak"], already)
    if to_unlock:
        await unlock_achievements(user_id, to_unlock)

    return {
        "streak": transition["current_streak"],
        "isNewDay": transition["isNewDay"],
        "achievementsUnlocked": to_unlock,
    }
