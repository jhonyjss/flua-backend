"""Help answer — port of help-answer.post.ts."""
from app.core.config import get_settings
from app.schemas.ai import HelpAnswerRequest, HelpAnswerResult
from app.services.anthropic_client import complete, extract_json

SYSTEM_PROMPT = """You are a bilingual English teacher (Portuguese/English) helping a Brazilian student.
The student clicked "Help me answer" because they don't know how to respond.

Give a SHORT explanation in Portuguese and ONE example answer in English.
Respond ONLY with JSON: {"explanationPt": str, "exampleAnswer": str}"""


def _user_prompt(req: HelpAnswerRequest) -> str:
    parts = [f'The teacher asked: "{req.npcQuestion}"']
    if req.lessonContext:
        lc = req.lessonContext
        parts.append(
            f"\nLesson context:\n- Topic: {lc.currentTopic} ({lc.currentTopicPt})\n"
            f"- Key phrases: {', '.join(lc.keyPhrases)}\n"
            f"- Grammar: {lc.grammarPoint}\n- Vocabulary: {', '.join(lc.vocabularyWords)}"
        )
    parts.append(f"\nStudent level: {req.userLevel}")
    if req.conversationHistory:
        recent = req.conversationHistory[-4:]
        parts.append(
            "\nRecent conversation:\n"
            + "\n".join(
                f"{'Student' if m.role == 'user' else 'Teacher'}: {m.message}" for m in recent
            )
        )
    parts.append("\nReturn ONLY valid JSON.")
    return "".join(parts)


async def help_answer(req: HelpAnswerRequest) -> HelpAnswerResult:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return HelpAnswerResult(
            success=True,
            explanationPt="Tente usar uma frase simples em inglês. Não se preocupe com erros!",
            exampleAnswer="Hello, my name is...",
        )
    try:
        raw = await complete(
            SYSTEM_PROMPT,
            _user_prompt(req),
            max_tokens=512,
            temperature=0.3,
            model=settings.anthropic_model_haiku,
        )
        data = extract_json(raw)
        return HelpAnswerResult(
            success=True,
            explanationPt=data.get("explanationPt", ""),
            exampleAnswer=data.get("exampleAnswer", ""),
        )
    except (ValueError, Exception) as exc:
        return HelpAnswerResult(success=False, error=str(exc) or "Não foi possível responder agora.")
