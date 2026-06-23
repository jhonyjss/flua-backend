"""Hybrid lesson evaluation orchestrator.

Combines deterministic skill signals (objective, computed from real lesson data)
with an LLM judge (Claude Haiku, versioned rubric) into final per-skill scores,
then upserts the result. The LLM failing never blocks the student — we fall back
to the deterministic-only scores. The transcript is never persisted; only short
`evidence` snippets the model picked are stored.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.schemas.evaluation import (
    EvaluateLessonRequest,
    FocusArea,
    LessonEvaluationResult,
    SkillScores,
)
from app.services import learning_intel
from app.services import supabase_admin as db
from app.services.ai.evaluation_scoring import (
    PROMPT_VERSION,
    SKILLS,
    blend,
    completion_rate,
    sanitize_llm_scores,
    should_skip,
)
from app.services.ai.lesson_extraction import parse_extraction
from app.services.ai.skill_signals import compute_deterministic
from app.services.anthropic_client import complete, extract_json

logger = logging.getLogger(__name__)

_TRANSCRIPT_CHAR_CAP = 8000


def build_transcript(turns: list) -> str:
    """Render turns as 'Aluno:'/'Flua:' lines, keeping the END of the class
    (most representative of where the student got to)."""
    lines = [
        f"{'Aluno' if t.role == 'student' else 'Flua'}: {t.text.strip()}"
        for t in turns
        if t.text.strip()
    ]
    text = "\n".join(lines)
    return text[-_TRANSCRIPT_CHAR_CAP:] if len(text) > _TRANSCRIPT_CHAR_CAP else text


def build_judge_system_prompt(req: EvaluateLessonRequest) -> str:
    vocab = ", ".join(req.lessonContext.vocabulary[:20]) or "—"
    return (
        "Você é uma avaliadora de inglês criteriosa e justa. Avalie a fala do ALUNO "
        "(linhas 'Aluno:') numa aula ao vivo, ignorando as falas da professora ('Flua:'). "
        f"Idioma alvo: {req.language}. Nível do aluno: {req.level}. "
        f"Tema da aula: {req.lessonContext.title or '—'}. "
        f"Foco gramatical: {req.lessonContext.grammarFocus or '—'}. "
        f"Vocabulário-alvo: {vocab}.\n\n"
        "Dê uma nota 0–100 para cada habilidade, calibrada ao nível do aluno (não puna "
        "deslizes pequenos em níveis iniciais):\n"
        "- grammar: correção dos tempos/estruturas, especialmente o foco da aula.\n"
        "- vocabulary: uso do vocabulário-alvo + variedade e adequação.\n"
        "- pronunciation: SÓ dá pra inferir por correções/transcrições estranhas — seja "
        "conservadora e use nota próxima da média se não houver sinal claro.\n"
        "- conversation: fluência funcional — turnos completos, iniciativa, respostas adequadas.\n"
        "- comprehension: entendeu o que a Flua pediu? Precisou de repetição?\n\n"
        "Responda APENAS com um objeto JSON, exatamente com estas chaves:\n"
        '{"grammar": int, "vocabulary": int, "pronunciation": int, "conversation": int, '
        '"comprehension": int, "summaryPt": str (2-3 frases, 2ª pessoa, encorajador), '
        '"strengths": [str em PT], '
        '"focusAreas": [{"title": str PT, "description": str PT, '
        '"severity": "high"|"medium"|"low", "skill": "grammar"|"vocabulary"|"pronunciation"|"conversation"|"comprehension"}], '
        '"evidence": [str — trechos curtos da fala do aluno que justificam as notas], '
        '"vocabulary": [{"term": str (palavra/expressão em inglês que o aluno praticou ou deveria fixar), '
        '"type": "word"|"phrase"|"collocation"|"phrasal_verb"|"idiom", "meaning_pt": str, "example": str em inglês}] '
        "(no máximo 8, priorize o vocabulário-alvo de fato usado/visto), "
        '"errors": [{"error": str (trecho REAL e errado da fala do aluno, em inglês), "correction": str, '
        '"category": "grammar"|"vocabulary"|"pronunciation"|"other", "example_wrong": str, "example_correct": str}] '
        "(no máximo 6, só erros reais e recorrentes; [] se não houver)}"
    )


def _parse_focus_areas(raw: object) -> list[FocusArea]:
    out: list[FocusArea] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        try:
            out.append(FocusArea.model_validate(item))
        except Exception:  # noqa: BLE001 — skip malformed entries
            continue
    return out


async def _judge(req: EvaluateLessonRequest) -> dict:
    """Run the LLM judge. Returns {} on any failure (caller falls back to det)."""
    transcript = build_transcript(req.turns)
    if not transcript:
        return {}
    settings = get_settings()
    raw = await complete(
        build_judge_system_prompt(req),
        transcript,
        max_tokens=1300,
        temperature=0.2,
        model=settings.anthropic_model_haiku,
    )
    return extract_json(raw)


async def evaluate_lesson(user_id: str, req: EvaluateLessonRequest) -> LessonEvaluationResult:
    student_turns = [t for t in req.turns if t.role == "student"]
    if should_skip(len(student_turns)):
        return LessonEvaluationResult(success=True, skipped=True, turnsCount=len(student_turns))

    deterministic = compute_deterministic(
        [{"role": t.role, "text": t.text} for t in req.turns],
        target_vocab=req.lessonContext.vocabulary,
        corrections_received=req.sessionMetrics.correctionsReceived,
        completion_rate=completion_rate(
            req.sessionMetrics.objectivesCompleted, req.sessionMetrics.objectivesTotal
        ),
        phrase_scores=req.phraseScores or None,
        stt_confidence=req.sttConfidence,
    )
    det_scores = {k: deterministic[k] for k in SKILLS}

    # ── LLM judge (never blocks; falls back to deterministic) ──
    llm_scores: dict[str, int] = {}
    summary_pt: str | None = None
    strengths: list[str] = []
    focus_areas: list[FocusArea] = []
    evidence: list[str] = []
    model_used: str | None = None
    extracted_vocab: list[dict] = []
    extracted_errors: list[dict] = []
    try:
        data = await _judge(req)
        if data:
            llm_scores = sanitize_llm_scores(data)
            raw_summary = data.get("summaryPt")
            summary_pt = str(raw_summary)[:600] if raw_summary else None
            strengths = [str(s)[:160] for s in (data.get("strengths") or [])][:5]
            focus_areas = _parse_focus_areas(data.get("focusAreas"))
            evidence = [str(e)[:200] for e in (data.get("evidence") or [])][:6]
            extracted_vocab, extracted_errors = parse_extraction(data)
            model_used = get_settings().anthropic_model_haiku
    except Exception as err:  # noqa: BLE001 — degrade gracefully to deterministic
        logger.warning("evaluate_lesson: LLM judge failed, using deterministic only: %s", err)

    scores = blend(det_scores, llm_scores)
    confidence = float(deterministic["confidence"])

    row = {
        "user_id": user_id,
        "session_id": req.sessionId,
        "lesson_id": req.lessonId,
        "language": req.language,
        **scores,
        "deterministic": det_scores,
        "llm_scores": llm_scores,
        "summary_pt": summary_pt,
        "strengths": strengths,
        "focus_areas": [f.model_dump() for f in focus_areas],
        "evidence": evidence,
        "turns_count": deterministic["turns_count"],
        "confidence": confidence,
        "model": model_used,
        "prompt_version": PROMPT_VERSION,
    }
    try:
        await db.upsert("lesson_skill_evaluations", row, on_conflict="user_id,session_id")
    except Exception as err:  # noqa: BLE001 — persistence failure must not break the lesson
        logger.error("evaluate_lesson: upsert failed: %s", err)

    # Feed the learning-intelligence memory (vocabulary + recurring errors) from
    # this lesson. Best-effort and isolated by user_id — never blocks completion.
    if extracted_vocab or extracted_errors:
        try:
            await learning_intel.save_lesson_extraction(user_id, extracted_vocab, extracted_errors)
        except Exception as err:  # noqa: BLE001 — extraction is a bonus, never fatal
            logger.warning("evaluate_lesson: extraction persistence failed: %s", err)

    return LessonEvaluationResult(
        success=True,
        scores=SkillScores(**scores),
        deterministic=det_scores,
        llmScores=llm_scores,
        summaryPt=summary_pt,
        strengths=strengths,
        focusAreas=focus_areas,
        evidence=evidence,
        confidence=confidence,
        turnsCount=deterministic["turns_count"],
    )
