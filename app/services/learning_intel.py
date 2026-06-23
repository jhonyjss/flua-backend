"""Learning-intelligence repository + service (Supabase REST).

Every function takes the authenticated `user_id` (from the JWT in the router) and
filters by it — the service-role key bypasses RLS, so this filter is the security
boundary. `user_id` is NEVER read from a request body.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.schemas.learning_intel import (
    ErrorCreate,
    ErrorLog,
    LearningProfile,
    LearningProfilePatch,
    Recommendation,
    ReviewItem,
    VocabularyCreate,
    VocabularyItem,
    VocabularyPatch,
)
from app.services import supabase_admin as db
from app.services.ai.recommendation import recommend_next
from app.services.ai.spaced_repetition import SrsState, review

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _due_iso(days: int) -> str:
    return (_now() + timedelta(days=days)).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ── Profile ──────────────────────────────────────────────────────────────
def _profile(row: dict | None) -> LearningProfile:
    if not row:
        return LearningProfile()
    return LearningProfile(
        level=row.get("level", "A1"),
        native_language=row.get("native_language", "pt-BR"),
        learning_goal=row.get("learning_goal"),
        strengths=row.get("strengths") or [],
        weaknesses=row.get("weaknesses") or [],
        preferred_explanation_language=row.get("preferred_explanation_language", "pt-BR"),
        pace=row.get("pace", "calm"),
    )


async def get_profile(user_id: str) -> LearningProfile:
    return _profile(await db.select_one("learning_profiles", {"user_id": user_id}))


async def upsert_profile(user_id: str, patch: LearningProfilePatch) -> LearningProfile:
    values = patch.model_dump(exclude_none=True)
    values["user_id"] = user_id
    values["updated_at"] = _now_iso()
    await db.upsert("learning_profiles", values, on_conflict="user_id")
    return await get_profile(user_id)


# ── Vocabulary ───────────────────────────────────────────────────────────
def _vocab(row: dict) -> VocabularyItem:
    return VocabularyItem(
        id=row["id"],
        term=row["term"],
        type=row.get("type", "word"),
        level=row.get("level"),
        meaning_pt=row.get("meaning_pt"),
        examples=row.get("examples") or [],
        status=row.get("status", "new"),
        confidence_score=float(row.get("confidence_score") or 0.30),
        times_seen=row.get("times_seen") or 0,
        times_correct=row.get("times_correct") or 0,
        next_review_at=row.get("next_review_at"),
    )


async def list_vocabulary(user_id: str, status: str | None = None) -> list[VocabularyItem]:
    filters = {"user_id": user_id}
    if status:
        filters["status"] = status
    rows = await db.select_many("vocabulary_items", filters, order="created_at.desc", limit=200)
    return [_vocab(r) for r in rows]


async def create_vocabulary(user_id: str, body: VocabularyCreate) -> VocabularyItem:
    due = _due_iso(1)  # first review tomorrow
    await db.upsert(
        "vocabulary_items",
        {
            "user_id": user_id, "term": body.term, "type": body.type, "level": body.level,
            "meaning_pt": body.meaning_pt, "examples": body.examples, "status": "new",
            "confidence_score": 0.30, "next_review_at": due, "updated_at": _now_iso(),
        },
        on_conflict="user_id,term,type",
    )
    row = await db.select_one("vocabulary_items", {"user_id": user_id, "term": body.term, "type": body.type})
    if not row:
        raise HTTPException(500, "Falha ao salvar vocabulário")
    # Enqueue a spaced-review item (idempotent per vocab).
    await db.upsert(
        "review_items",
        {"user_id": user_id, "kind": "vocabulary", "ref_id": row["id"], "due_at": due, "status": "due", "updated_at": _now_iso()},
        on_conflict="user_id,kind,ref_id",
    )
    return _vocab(row)


async def update_vocabulary(user_id: str, item_id: str, patch: VocabularyPatch) -> VocabularyItem:
    values = patch.model_dump(exclude_none=True)
    if not values:
        row = await db.select_one("vocabulary_items", {"id": item_id, "user_id": user_id})
        if not row:
            raise HTTPException(404, "Vocabulário não encontrado")
        return _vocab(row)
    values["updated_at"] = _now_iso()
    await db.update("vocabulary_items", {"id": item_id, "user_id": user_id}, values)
    row = await db.select_one("vocabulary_items", {"id": item_id, "user_id": user_id})
    if not row:
        raise HTTPException(404, "Vocabulário não encontrado")
    return _vocab(row)


# ── Errors ───────────────────────────────────────────────────────────────
def _error(row: dict) -> ErrorLog:
    return ErrorLog(
        id=row["id"],
        error_text=row["error_text"],
        correction=row["correction"],
        category=row.get("category", "other"),
        count=row.get("count") or 1,
        examples=row.get("examples") or [],
        last_seen_at=row.get("last_seen_at"),
    )


async def list_errors(user_id: str) -> list[ErrorLog]:
    rows = await db.select_many("error_logs", {"user_id": user_id}, order="count.desc", limit=100)
    return [_error(r) for r in rows]


async def record_error(user_id: str, body: ErrorCreate) -> ErrorLog:
    example = {"wrong": body.example_wrong, "correct": body.example_correct} if body.example_wrong else None
    existing = await db.select_one(
        "error_logs", {"user_id": user_id, "error_text": body.error_text, "correction": body.correction}
    )
    if existing:
        examples = existing.get("examples") or []
        if example:
            examples = (examples + [example])[-5:]
        new_count = (existing.get("count") or 1) + 1
        await db.update(
            "error_logs", {"id": existing["id"], "user_id": user_id},
            {"count": new_count, "last_seen_at": _now_iso(), "examples": examples},
        )
        return _error({**existing, "count": new_count, "examples": examples})

    created = await db.insert(
        "error_logs",
        {
            "user_id": user_id, "error_text": body.error_text, "correction": body.correction,
            "category": body.category, "count": 1, "examples": [example] if example else [],
            "last_seen_at": _now_iso(),
        },
    )
    return _error(created)


# ── Automatic extraction (from a finished lesson) ────────────────────────
async def save_lesson_extraction(
    user_id: str, vocab: list[dict], errors: list[dict]
) -> dict:
    """Persist vocabulary + recurring errors extracted from a lesson transcript.

    Best-effort: each item is isolated so one bad row never blocks the rest, and
    a failure here must never break lesson completion. Reuses `create_vocabulary`
    (which also enqueues a spaced-review) and `record_error` (which dedupes +
    increments counts). Returns how many of each were saved.
    """
    saved_vocab = 0
    for v in vocab:
        try:
            await create_vocabulary(user_id, VocabularyCreate(**v))
            saved_vocab += 1
        except Exception as err:  # noqa: BLE001 — skip one bad item, keep going
            logger.warning("save_lesson_extraction: vocab skipped: %s", err)

    saved_errors = 0
    for e in errors:
        try:
            await record_error(user_id, ErrorCreate(**e))
            saved_errors += 1
        except Exception as err:  # noqa: BLE001 — skip one bad item, keep going
            logger.warning("save_lesson_extraction: error skipped: %s", err)

    return {"vocabulary": saved_vocab, "errors": saved_errors}


# ── Reviews (spaced repetition) ──────────────────────────────────────────
async def reviews_today(user_id: str) -> list[ReviewItem]:
    rows = await db.select_many("review_items", {"user_id": user_id, "status": "due"}, order="due_at.asc", limit=100)
    now = _now()
    rows = [r for r in rows if (_parse(r.get("due_at")) or now) <= now]
    if not rows:
        return []

    vocab_ids = [r["ref_id"] for r in rows if r["kind"] == "vocabulary"]
    error_ids = [r["ref_id"] for r in rows if r["kind"] == "error"]
    vocab_map = {
        v["id"]: v
        for v in (await db.select_many("vocabulary_items", {"user_id": user_id}, in_filters={"id": vocab_ids}) if vocab_ids else [])
    }
    error_map = {
        e["id"]: e
        for e in (await db.select_many("error_logs", {"user_id": user_id}, in_filters={"id": error_ids}) if error_ids else [])
    }

    out: list[ReviewItem] = []
    for r in rows:
        item = ReviewItem(
            id=r["id"], kind=r["kind"], ref_id=r["ref_id"], due_at=r.get("due_at"),
            interval_days=r.get("interval_days") or 0, reps=r.get("reps") or 0, status=r.get("status", "due"),
        )
        if r["kind"] == "vocabulary" and r["ref_id"] in vocab_map:
            v = vocab_map[r["ref_id"]]
            item.term, item.meaning_pt = v.get("term"), v.get("meaning_pt")
        elif r["kind"] == "error" and r["ref_id"] in error_map:
            e = error_map[r["ref_id"]]
            item.term, item.correction = e.get("error_text"), e.get("correction")
        out.append(item)
    return out


async def answer_review(user_id: str, review_id: str, quality: int) -> ReviewItem:
    r = await db.select_one("review_items", {"id": review_id, "user_id": user_id})
    if not r:
        raise HTTPException(404, "Revisão não encontrada")

    vocab = None
    confidence = 0.30
    if r["kind"] == "vocabulary":
        vocab = await db.select_one("vocabulary_items", {"id": r["ref_id"], "user_id": user_id})
        if vocab:
            confidence = float(vocab.get("confidence_score") or 0.30)

    state = SrsState(
        ease=float(r.get("ease") or 2.5), interval_days=r.get("interval_days") or 0,
        reps=r.get("reps") or 0, lapses=r.get("lapses") or 0, confidence=confidence, status="reviewing",
    )
    new = review(state, quality)
    due = _due_iso(new.interval_days)

    await db.update(
        "review_items", {"id": review_id, "user_id": user_id},
        {
            "ease": new.ease, "interval_days": new.interval_days, "reps": new.reps, "lapses": new.lapses,
            "due_at": due, "status": "done" if new.status == "mastered" else "due", "updated_at": _now_iso(),
        },
    )

    if r["kind"] == "vocabulary" and vocab:
        await db.update(
            "vocabulary_items", {"id": r["ref_id"], "user_id": user_id},
            {
                "confidence_score": new.confidence, "status": new.status, "next_review_at": due,
                "times_seen": (vocab.get("times_seen") or 0) + 1,
                "times_correct": (vocab.get("times_correct") or 0) + (1 if quality >= 3 else 0),
                "last_seen_at": _now_iso(), "updated_at": _now_iso(),
            },
        )

    return ReviewItem(
        id=review_id, kind=r["kind"], ref_id=r["ref_id"], due_at=due,
        interval_days=new.interval_days, reps=new.reps, status="due",
    )


# ── Recommendation ───────────────────────────────────────────────────────
async def recommend(user_id: str, minutes_available: int = 10) -> Recommendation:
    profile = await get_profile(user_id)
    errors = await db.select_many("error_logs", {"user_id": user_id}, order="count.desc", limit=5)
    vocab = await db.select_many("vocabulary_items", {"user_id": user_id}, order="next_review_at.asc", limit=50)
    now = _now()
    due_vocab = [
        {"term": v["term"], "type": v.get("type")}
        for v in vocab
        if v.get("status") != "mastered" and (_parse(v.get("next_review_at")) or now + timedelta(days=1)) <= now
    ]
    out = recommend_next(
        profile=profile.model_dump(),
        top_errors=errors,
        due_vocab=due_vocab,
        lesson_in_progress=None,
        minutes_available=minutes_available,
    )
    return Recommendation(**out)
