"""Stories contract — the same JSON the site's Nitro routes (server/api/stories/*) answered, so the
web and the app read one shape. Field names are snake_case on purpose: they are the table columns."""
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

QUESTIONS_PER_STORY = 5


class StoryProgress(BaseModel):
    step: str
    quiz_score: int | None = None
    xp_earned: int = 0
    completed_at: str | None = None


class StoryQuota(BaseModel):
    limit: int | None
    used: int
    remaining: int | None
    allowed: bool


class StoryStats(BaseModel):
    xp: int
    streak: int


class StoryListItem(BaseModel):
    id: str
    title: str
    cefr_level: str
    topic: str
    word_count: int
    created_at: str | None = None
    # One of the free stories (open to every account in the app).
    free: bool = False
    progress: StoryProgress | None = None


class StoryListResponse(BaseModel):
    success: bool = True
    stories: list[StoryListItem]
    quota: StoryQuota
    stats: StoryStats


class Story(BaseModel):
    id: str
    title: str
    cefr_level: str
    topic: str
    passage: str
    word_count: int
    audio_url: str | None = None
    audio_voice: str | None = None
    audio_alignment: Any = None


class StoryExpression(BaseModel):
    id: str
    expression: str
    occurrence_index: int
    part_of_speech: str
    phonetic: str
    definition_en: str
    definition_pt: str
    sort_order: int
    audio_url: str | None = None


class StoryQuestion(BaseModel):
    id: str
    question: str
    options: Any
    correct_index: int
    explanation: str
    sort_order: int


class OpenStoryResponse(BaseModel):
    success: bool = True
    story: Story
    expressions: list[StoryExpression]
    questions: list[StoryQuestion]
    progress: StoryProgress
    quota: StoryQuota
    stats: StoryStats


class StoryProgressRequest(BaseModel):
    step: Literal["reading", "vocab", "quiz"]


class StoryProgressResponse(BaseModel):
    success: bool = True
    step: str


class CompleteStoryRequest(BaseModel):
    # One answer per question, an option index 0..3; strict, so a boolean is not read as 0/1 (zod refused it too).
    answers: list[Annotated[int, Field(strict=True, ge=0, le=3)]] = Field(
        min_length=QUESTIONS_PER_STORY, max_length=QUESTIONS_PER_STORY,
    )


class CompleteStoryResponse(BaseModel):
    success: bool = True
    alreadyCompleted: bool
    correctCount: int
    total: int
    xpEarned: int
    quizScore: int | None
    streak: int
