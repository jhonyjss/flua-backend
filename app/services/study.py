"""Vocabulary + content-bank data (ported from useProgress / useFlashcards / useLessons).

`compute_vocabulary_summary` is a pure helper (unit-tested without network).
"""
import asyncio
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Awaitable, Callable, TypeVar

from app.services import supabase_admin as db

T = TypeVar("T")
CONTENT_CACHE_TTL_SECONDS = 600
_content_cache: dict[str, tuple[float, object]] = {}
_content_promises: dict[str, asyncio.Task[object]] = {}


async def _cached_content(key: str, loader: Callable[[], Awaitable[T]]) -> T:
    cached = _content_cache.get(key)
    now = monotonic()
    if cached and cached[0] > now:
        return cached[1]  # type: ignore[return-value]

    pending = _content_promises.get(key)
    if pending is not None:
        return await pending  # type: ignore[return-value]

    request = asyncio.create_task(loader())
    _content_promises[key] = request
    try:
        value = await request
        _content_cache[key] = (monotonic() + CONTENT_CACHE_TTL_SECONDS, value)
        return value
    finally:
        _content_promises.pop(key, None)


def compute_vocabulary_summary(words: list[dict]) -> dict:
    """total / learning / mastered / dueForReview — mirrors getVocabularySummary."""
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    def due(word: dict) -> bool:
        level = word.get("mastery_level") or 0
        if level >= 5:
            return False
        last = word.get("last_reviewed_at")
        if not last:
            return True
        try:
            return datetime.fromisoformat(last.replace("Z", "+00:00")) < one_day_ago
        except (ValueError, AttributeError):
            return True

    return {
        "total": len(words),
        "learning": sum(1 for w in words if 0 < (w.get("mastery_level") or 0) < 5),
        "mastered": sum(1 for w in words if (w.get("mastery_level") or 0) == 5),
        "dueForReview": sum(1 for w in words if due(w)),
    }


async def vocabulary_summary(user_id: str) -> dict:
    words = await db.select_many("user_vocabulary", {"user_id": user_id})
    return compute_vocabulary_summary(words)


async def list_vocabulary(user_id: str, room_id: int | None = None) -> list[dict]:
    filters = {"user_id": user_id}
    if room_id is not None:
        filters["room_id"] = str(room_id)
    return await db.select_many("user_vocabulary", filters, order="created_at.desc")


async def save_vocabulary_word(user_id: str, payload: dict) -> dict:
    """Insert or bump an existing word (idempotent on user_id+word)."""
    existing = await db.select_many(
        "user_vocabulary", {"user_id": user_id, "word": payload["word"]}, select="id", limit=1,
    )
    if existing:
        await db.update("user_vocabulary", {"id": str(existing[0]["id"])}, {
            "translation": payload.get("translation", ""),
            "last_reviewed_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"updated": True, "id": existing[0]["id"]}
    created = await db.insert("user_vocabulary", {
        "user_id": user_id,
        "word": payload["word"],
        "translation": payload.get("translation", ""),
        "example_sentence": payload.get("example", ""),
        "category": payload.get("source", ""),
        "room_id": payload.get("roomId"),
        "mastery_level": 0,
        "times_seen": 1,
        "times_correct": 0,
        "last_reviewed_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"updated": False, "id": (created or {}).get("id")}


async def grammar_progress(user_id: str) -> list[dict]:
    return await db.select_many("user_grammar_progress", {"user_id": user_id})


# ── Content banks (not user-scoped) ───────────────────────────────────

async def speaking_classes(level: str | None = None) -> list[dict]:
    async def load() -> list[dict]:
        filters = {"is_published": "true"}
        if level:
            filters["level"] = level
        return await db.select_many("speaking_classes", filters, order="order_index.asc")

    return await _cached_content(f"speaking_classes:{level or 'all'}", load)


async def grammar_bank(level: str | None = None) -> list[dict]:
    async def load() -> list[dict]:
        filters: dict[str, str] = {}
        if level:
            filters["level"] = level
        return await db.select_many("grammar_bank", filters)

    return await _cached_content(f"grammar_bank:{level or 'all'}", load)


async def vocabulary_bank(level: str | None = None) -> list[dict]:
    async def load() -> list[dict]:
        filters: dict[str, str] = {}
        if level:
            filters["level"] = level
        return await db.select_many("vocabulary_bank", filters)

    return await _cached_content(f"vocabulary_bank:{level or 'all'}", load)
