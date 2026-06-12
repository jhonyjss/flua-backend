"""AI endpoints — Anthropic-backed (parity with server/api/ai/*)."""
import logging

from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.core.auth import AuthUser
from app.core.rate_limit import rate_limited
from app.schemas.ai import (
    ConversationResponseRequest,
    ConversationResponseResult,
    GrammarAnalysisRequest,
    GrammarAnalysisResult,
    HelpAnswerRequest,
    HelpAnswerResult,
    LearningRecommendationsRequest,
    LearningRecommendationsResult,
)
from app.schemas.speech import TranscribeResponse
from app.services import ai_endpoints as prompts
from app.services import stt
from app.services.anthropic_client import complete, extract_json

logger = logging.getLogger("flueai.ai")
router = APIRouter(prefix="/api/ai", tags=["ai"])

# Per-user limits mirror the Nuxt rate limiter usage (generous but bounded).
ai_guard = rate_limited("ai", max_requests=60, window_seconds=60)


@router.post("/grammar-analysis", response_model=GrammarAnalysisResult)
async def grammar_analysis(
    body: GrammarAnalysisRequest, user: AuthUser = Depends(ai_guard),
) -> GrammarAnalysisResult:
    try:
        raw = await complete(
            prompts.build_grammar_system_prompt(body),
            body.userMessage,
            max_tokens=1024,
            temperature=0.2,
        )
        return prompts.parse_grammar_result(raw)
    except ValueError as err:
        logger.warning("grammar-analysis parse failure for user %s: %s", user.id, err)
        return GrammarAnalysisResult(success=False, error="Não foi possível analisar agora.")


@router.post("/conversation-response", response_model=ConversationResponseResult)
async def conversation_response(
    body: ConversationResponseRequest, user: AuthUser = Depends(ai_guard),
) -> ConversationResponseResult:
    messages = [{"role": t.role, "content": t.content} for t in body.messages]
    reply = await complete(
        prompts.build_conversation_system_prompt(body),
        "",
        messages=messages,
        max_tokens=512,
        temperature=0.7,
    )
    return ConversationResponseResult(success=True, reply=reply.strip())


@router.post("/help-answer", response_model=HelpAnswerResult)
async def help_answer(
    body: HelpAnswerRequest, user: AuthUser = Depends(ai_guard),
) -> HelpAnswerResult:
    try:
        raw = await complete(
            prompts.build_help_system_prompt(body), body.question, max_tokens=600, temperature=0.3,
        )
        data = extract_json(raw)
        return HelpAnswerResult(success=True, answer=data.get("answer", ""), answerPt=data.get("answerPt", ""))
    except ValueError:
        return HelpAnswerResult(success=False, error="Não foi possível responder agora.")


@router.post("/learning-recommendations", response_model=LearningRecommendationsResult)
async def learning_recommendations(
    body: LearningRecommendationsRequest, user: AuthUser = Depends(ai_guard),
) -> LearningRecommendationsResult:
    try:
        raw = await complete(
            prompts.build_recommendations_system_prompt(),
            prompts.build_recommendations_user_message(body),
            max_tokens=900,
            temperature=0.4,
        )
        return prompts.parse_recommendations_result(raw)
    except ValueError as err:
        logger.warning("recommendations parse failure for user %s: %s", user.id, err)
        return LearningRecommendationsResult(success=False, error="Não foi possível gerar recomendações.")


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("en"),
    user: AuthUser = Depends(rate_limited("stt", max_requests=120, window_seconds=60)),
) -> TranscribeResponse:
    data = await audio.read()
    if not data:
        return TranscribeResponse(success=False, error="Áudio vazio")
    transcript, confidence = await stt.transcribe(data, audio.content_type or "audio/webm", language)
    return TranscribeResponse(success=True, transcript=transcript, confidence=confidence)
