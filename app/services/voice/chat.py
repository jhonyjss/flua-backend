"""Voice chat — OpenAI Responses API with server-owned tutor prompt."""
from app.schemas.voice import VoiceChatRequest
from app.services.openai_client import chat_responses
from app.services.tutor_instructions import build_tutor_instructions, cap_lesson_context
from app.utils.voice_chat import sanitize_conversation_turns


async def voice_chat(body: VoiceChatRequest) -> str:
    turns = sanitize_conversation_turns([m.model_dump() for m in body.messages])
    if not turns:
        raise ValueError("No valid messages provided")
    system = build_tutor_instructions(
        body.level,
        body.scenario,
        cap_lesson_context(body.lessonContext),
        body.studentName,
        body.language,
    )
    messages = [{"role": "system", "content": system}, *turns]
    return await chat_responses(messages, model=body.model, max_tokens=body.maxTokens)
