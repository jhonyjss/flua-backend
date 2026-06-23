"""AI endpoints — full parity with server/api/ai/*."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import AuthUser
from app.core.rate_limit import rate_limited
from app.schemas.ai import (
    AssistRequest,
    AssistResult,
    ConversationResponseRequest,
    ConversationResponseResult,
    DynamicExamplesRequest,
    DynamicExamplesResult,
    GenerateClassRequest,
    GenerateClassResult,
    GenerateImageRequest,
    GenerateImageResult,
    GenerateRoomRequest,
    GenerateRoomResult,
    GenerateSuggestionsRequest,
    GenerateSuggestionsResult,
    GrammarAnalysisRequest,
    GrammarAnalysisResult,
    HelpAnswerRequest,
    HelpAnswerResult,
    LearningRecommendationsRequest,
    LearningRecommendationsResult,
    TranscribeJsonRequest,
    TranscribeResult,
    ValidateObjectiveRequest,
    ValidateObjectiveResult,
)
from app.schemas.evaluation import EvaluateLessonRequest, LessonEvaluationResult
from app.schemas.learning_intel import (
    RagDocumentIn,
    RagIngestResult,
    TutorRespondRequest,
    TutorRespondResult,
)
from app.schemas.speech import SpeechCorrectionRequest, SpeechCorrectionResponse
from app.services.ai.assist import assist
from app.services.ai.conversation import run_conversation
from app.services.ai.dynamic_examples import dynamic_examples
from app.services import supabase_admin as db
from app.services.ai import rag
from app.services.ai.evaluate_lesson import evaluate_lesson
from app.services.ai.tutor_respond import respond as tutor_respond
from app.services.ai.generate_class import generate_class
from app.services.ai.generate_image import generate_image
from app.services.ai.generate_room import generate_room
from app.services.ai.grammar import analyze_grammar
from app.services.ai.help_answer import help_answer
from app.services.ai.recommendations import learning_recommendations
from app.services.ai.suggestions import generate_suggestions
from app.services.ai.validate_objective import validate_objective
from app.services import stt
from app.services.speech_correction import correct_speech

logger = logging.getLogger("flueai.ai")
router = APIRouter(prefix="/api/ai", tags=["ai"])
ai_guard = rate_limited("ai", max_requests=60, window_seconds=60)


@router.post("/grammar-analysis", response_model=GrammarAnalysisResult)
async def grammar_analysis(body: GrammarAnalysisRequest, user: AuthUser = Depends(ai_guard)) -> GrammarAnalysisResult:
    return await analyze_grammar(body)


@router.post("/evaluate-lesson", response_model=LessonEvaluationResult)
async def evaluate_lesson_route(
    body: EvaluateLessonRequest, user: AuthUser = Depends(ai_guard),
) -> LessonEvaluationResult:
    return await evaluate_lesson(user.id, body)


@router.post("/tutor/respond", response_model=TutorRespondResult)
async def tutor_respond_route(
    body: TutorRespondRequest, user: AuthUser = Depends(ai_guard),
) -> TutorRespondResult:
    """Text tutor reply grounded in the student's profile + the pedagogical RAG,
    with anti-hallucination guardrails. Isolated by the authenticated user."""
    result = await tutor_respond(user.id, body.message, language=body.language, level=body.level)
    return TutorRespondResult(**result)


@router.post("/rag/ingest", response_model=RagIngestResult)
async def rag_ingest_route(body: RagDocumentIn, user: AuthUser = Depends(ai_guard)) -> RagIngestResult:
    """Ingest one verified pedagogical document into the RAG (admin only)."""
    profile = await db.select_one("profiles", {"id": user.id})
    if not profile or profile.get("role") != "admin":
        raise HTTPException(403, "Apenas administradores podem ingerir conteúdo do RAG.")
    count = await rag.ingest_document(body.model_dump())
    return RagIngestResult(document_title=body.title, chunks=count)


@router.post("/conversation-response", response_model=ConversationResponseResult)
async def conversation_response(
    body: ConversationResponseRequest, user: AuthUser = Depends(ai_guard),
) -> ConversationResponseResult:
    ok, response, err = await run_conversation(body)
    if not ok:
        return ConversationResponseResult(success=False, error=err or "Failed to generate response")
    return ConversationResponseResult(success=True, response=response)


@router.post("/help-answer", response_model=HelpAnswerResult)
async def help_answer_route(body: HelpAnswerRequest, user: AuthUser = Depends(ai_guard)) -> HelpAnswerResult:
    return await help_answer(body)


@router.post("/learning-recommendations", response_model=LearningRecommendationsResult)
async def learning_recommendations_route(
    body: LearningRecommendationsRequest, user: AuthUser = Depends(ai_guard),
) -> LearningRecommendationsResult:
    return await learning_recommendations(body)


@router.post("/validate-objective", response_model=ValidateObjectiveResult)
async def validate_objective_route(
    body: ValidateObjectiveRequest, user: AuthUser = Depends(ai_guard),
) -> ValidateObjectiveResult:
    return await validate_objective(body)


@router.post("/generate-suggestions", response_model=GenerateSuggestionsResult)
async def generate_suggestions_route(
    body: GenerateSuggestionsRequest, user: AuthUser = Depends(ai_guard),
) -> GenerateSuggestionsResult:
    return await generate_suggestions(body)


@router.post("/dynamic-examples", response_model=DynamicExamplesResult)
async def dynamic_examples_route(
    body: DynamicExamplesRequest, user: AuthUser = Depends(ai_guard),
) -> DynamicExamplesResult:
    return await dynamic_examples(body)


@router.post("/assist", response_model=AssistResult)
async def assist_route(body: AssistRequest, user: AuthUser = Depends(ai_guard)) -> AssistResult:
    return await assist(body)


@router.post("/generate-class", response_model=GenerateClassResult)
async def generate_class_route(body: GenerateClassRequest, user: AuthUser = Depends(ai_guard)) -> GenerateClassResult:
    return await generate_class(body)


@router.post("/generate-room", response_model=GenerateRoomResult)
async def generate_room_route(body: GenerateRoomRequest, user: AuthUser = Depends(ai_guard)) -> GenerateRoomResult:
    return await generate_room(body)


@router.post("/generate-image", response_model=GenerateImageResult)
async def generate_image_route(body: GenerateImageRequest, user: AuthUser = Depends(ai_guard)) -> GenerateImageResult:
    return await generate_image(body)


@router.post("/transcribe", response_model=TranscribeResult)
async def transcribe_route(
    request: Request,
    user: AuthUser = Depends(rate_limited("stt", max_requests=120, window_seconds=60)),
) -> TranscribeResult:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        audio = form.get("audio")
        language = str(form.get("language") or "en")
        if audio is None:
            return TranscribeResult(success=False, error="Áudio vazio")
        data = await audio.read()  # type: ignore[union-attr]
        if not data:
            return TranscribeResult(success=False, error="Áudio vazio")
        mime = getattr(audio, "content_type", None) or "audio/webm"  # type: ignore[union-attr]
        return await stt.transcribe_file(data, mime, language)
    body = TranscribeJsonRequest.model_validate(await request.json())
    return await stt.transcribe_json(body)


@router.post("/speech-correct", response_model=SpeechCorrectionResponse)
async def speech_correct(
    body: SpeechCorrectionRequest,
    user: AuthUser = Depends(rate_limited("speech-correct", max_requests=120, window_seconds=60)),
) -> SpeechCorrectionResponse:
    return await correct_speech(body)
