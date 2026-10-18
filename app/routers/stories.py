"""Stories routes, the same paths and answers as the site's Nitro routes (server/api/stories/*).

Bodies are validated here and refused with 400 (not FastAPI's 422), as the site did."""
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ValidationError

from app.core.auth import AuthUser, get_current_user
from app.schemas.stories import (
    CompleteStoryRequest,
    CompleteStoryResponse,
    OpenStoryResponse,
    StoryListResponse,
    StoryProgressRequest,
    StoryProgressResponse,
)
from app.services import stories

router = APIRouter(prefix="/api/stories", tags=["stories"])


def _parse[T: BaseModel](model: type[T], body: Any, message: str) -> T:
    try:
        return model.model_validate(body)
    except ValidationError as err:
        raise HTTPException(400, message) from err


@router.get("", response_model=StoryListResponse)
async def list_stories(user: AuthUser = Depends(get_current_user)) -> StoryListResponse:
    return StoryListResponse.model_validate(await stories.list_stories(user.id))


@router.post("/{story_id}/open", response_model=OpenStoryResponse)
async def open_story(story_id: str, user: AuthUser = Depends(get_current_user)) -> OpenStoryResponse:
    """Starting a new story spends the free week's quota (403 QUOTA_EXCEEDED past it); reopening never does."""
    return OpenStoryResponse.model_validate(await stories.open_story(user.id, stories.require_story_id(story_id)))


@router.post("/{story_id}/progress", response_model=StoryProgressResponse)
async def save_progress(
    story_id: str, body: Any = Body(None), user: AuthUser = Depends(get_current_user),
) -> StoryProgressResponse:
    sid = stories.require_story_id(story_id)
    request = _parse(StoryProgressRequest, body, "Etapa inválida.")
    return StoryProgressResponse.model_validate(await stories.save_step(user.id, sid, request.step))


@router.post("/{story_id}/complete", response_model=CompleteStoryResponse)
async def complete_story(
    story_id: str, body: Any = Body(None), user: AuthUser = Depends(get_current_user),
) -> CompleteStoryResponse:
    """Scores the quiz server-side; XP (10 + 2 per correct answer) and the streak are paid once."""
    sid = stories.require_story_id(story_id)
    request = _parse(CompleteStoryRequest, body, "Respostas inválidas.")
    return CompleteStoryResponse.model_validate(await stories.complete_story(user.id, sid, request.answers))
