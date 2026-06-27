"""Study endpoints — user vocabulary + content banks (parity with useProgress /
useFlashcards / useLessons / useGrammarBank / useVocabularyBank)."""
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from app.core.auth import AuthUser, get_current_user
from app.schemas.learning import (
    SaveResult,
    VocabularySummary,
    VocabularyWordRequest,
)
from app.services import study

# User-scoped vocabulary
user_router = APIRouter(prefix="/api/users/me", tags=["study"])
# Public content banks
content_router = APIRouter(prefix="/api/content", tags=["content"])


@user_router.get("/vocabulary/summary", response_model=VocabularySummary)
async def vocabulary_summary(user: AuthUser = Depends(get_current_user)) -> VocabularySummary:
    return VocabularySummary.model_validate(await study.vocabulary_summary(user.id))


@user_router.get("/vocabulary", response_model=list[dict[str, Any]])
async def list_vocabulary(
    roomId: int | None = Query(default=None),
    user: AuthUser = Depends(get_current_user),
) -> list[dict]:
    return await study.list_vocabulary(user.id, roomId)


@user_router.post("/vocabulary", response_model=SaveResult)
async def save_vocabulary(
    body: VocabularyWordRequest, user: AuthUser = Depends(get_current_user),
) -> SaveResult:
    try:
        data = await study.save_vocabulary_word(user.id, body.model_dump())
        return SaveResult(success=True, data=data)
    except Exception as err:  # surface a clean error to the client
        return SaveResult(success=False, error=str(err))


@user_router.get("/grammar-progress", response_model=list[dict[str, Any]])
async def grammar_progress(user: AuthUser = Depends(get_current_user)) -> list[dict]:
    return await study.grammar_progress(user.id)


@content_router.get("/speaking-classes", response_model=list[dict[str, Any]])
async def speaking_classes(
    response: Response,
    level: str | None = Query(default=None),
    user: AuthUser = Depends(get_current_user),
) -> list[dict]:
    response.headers["Cache-Control"] = "private, max-age=300, stale-while-revalidate=600"
    return await study.speaking_classes(level)


@content_router.get("/grammar-bank", response_model=list[dict[str, Any]])
async def grammar_bank(
    response: Response,
    level: str | None = Query(default=None),
    user: AuthUser = Depends(get_current_user),
) -> list[dict]:
    response.headers["Cache-Control"] = "private, max-age=300, stale-while-revalidate=600"
    return await study.grammar_bank(level)


@content_router.get("/vocabulary-bank", response_model=list[dict[str, Any]])
async def vocabulary_bank(
    response: Response,
    level: str | None = Query(default=None),
    user: AuthUser = Depends(get_current_user),
) -> list[dict]:
    response.headers["Cache-Control"] = "private, max-age=300, stale-while-revalidate=600"
    return await study.vocabulary_bank(level)
