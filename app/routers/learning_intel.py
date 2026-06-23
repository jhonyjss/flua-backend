"""Learning-intelligence endpoints: profile, vocabulary (SRS), recurring errors,
spaced reviews and personalized recommendations.

Every endpoint is authenticated and isolated by user_id — the id comes from the
JWT (`get_current_user`), NEVER from the request body.
"""

from fastapi import APIRouter, Depends, Query

from app.core.auth import AuthUser, get_current_user
from app.schemas.learning_intel import (
    ErrorCreate,
    ErrorLog,
    LearningProfile,
    LearningProfilePatch,
    Recommendation,
    ReviewAnswer,
    ReviewItem,
    VocabularyCreate,
    VocabularyItem,
    VocabularyPatch,
)
from app.services import learning_intel as svc

router = APIRouter(prefix="/api/users/me", tags=["learning-intel"])


# ── Profile ──────────────────────────────────────────────────────────────
@router.get("/learning/profile", response_model=LearningProfile)
async def get_profile(user: AuthUser = Depends(get_current_user)) -> LearningProfile:
    return await svc.get_profile(user.id)


@router.patch("/learning/profile", response_model=LearningProfile)
async def patch_profile(
    body: LearningProfilePatch, user: AuthUser = Depends(get_current_user),
) -> LearningProfile:
    return await svc.upsert_profile(user.id, body)


# ── Vocabulary ───────────────────────────────────────────────────────────
@router.get("/learning/vocabulary", response_model=list[VocabularyItem])
async def list_vocabulary(
    status: str | None = Query(None), user: AuthUser = Depends(get_current_user),
) -> list[VocabularyItem]:
    return await svc.list_vocabulary(user.id, status)


@router.post("/learning/vocabulary", response_model=VocabularyItem, status_code=201)
async def create_vocabulary(
    body: VocabularyCreate, user: AuthUser = Depends(get_current_user),
) -> VocabularyItem:
    return await svc.create_vocabulary(user.id, body)


@router.patch("/learning/vocabulary/{item_id}", response_model=VocabularyItem)
async def patch_vocabulary(
    item_id: str, body: VocabularyPatch, user: AuthUser = Depends(get_current_user),
) -> VocabularyItem:
    return await svc.update_vocabulary(user.id, item_id, body)


# ── Errors ───────────────────────────────────────────────────────────────
@router.get("/learning/errors", response_model=list[ErrorLog])
async def list_errors(user: AuthUser = Depends(get_current_user)) -> list[ErrorLog]:
    return await svc.list_errors(user.id)


@router.post("/learning/errors", response_model=ErrorLog, status_code=201)
async def record_error(body: ErrorCreate, user: AuthUser = Depends(get_current_user)) -> ErrorLog:
    return await svc.record_error(user.id, body)


# ── Reviews (spaced repetition) ──────────────────────────────────────────
@router.get("/learning/reviews/today", response_model=list[ReviewItem])
async def reviews_today(user: AuthUser = Depends(get_current_user)) -> list[ReviewItem]:
    return await svc.reviews_today(user.id)


@router.post("/learning/reviews/{review_id}/answer", response_model=ReviewItem)
async def answer_review(
    review_id: str, body: ReviewAnswer, user: AuthUser = Depends(get_current_user),
) -> ReviewItem:
    return await svc.answer_review(user.id, review_id, body.quality)


# ── Recommendation ───────────────────────────────────────────────────────
@router.get("/learning/recommendations/next", response_model=Recommendation)
async def recommend_next(
    minutes: int = Query(10, ge=1, le=120), user: AuthUser = Depends(get_current_user),
) -> Recommendation:
    return await svc.recommend(user.id, minutes)
