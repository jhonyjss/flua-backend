"""Text tutor reply (/ai/tutor/respond): student profile + RAG + guardrails.

Isolated by user_id (passed from the router). Uses the learning profile to adapt,
RAG only for pedagogical content, and anti-hallucination rules + low temperature
to avoid making things up. The transcript/message is never persisted here.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.schemas.learning_intel import LearningProfile
from app.services import learning_intel
from app.services.ai import guardrails, rag
from app.services.anthropic_client import complete


def build_system_prompt(profile: LearningProfile, context: str, sufficient: bool) -> str:
    weaknesses = ", ".join(profile.weaknesses) or "—"
    rag_block = f"\n\n# Conteúdo pedagógico (RAG — use para explicar)\n{context}" if context else ""
    return (
        "Você é a Flua, tutora de inglês para brasileiros. Respostas curtas (1–3 "
        "frases), claras, em português do Brasil, com exemplos práticos curtos em inglês.\n\n"
        "# Perfil do aluno (use para adaptar dificuldade, ritmo e exemplos)\n"
        f"Nível CEFR: {profile.level}. Idioma de explicação: {profile.preferred_explanation_language}. "
        f"Ritmo: {profile.pace}. Pontos de atenção: {weaknesses}. "
        f"Objetivo: {profile.learning_goal or '—'}.\n\n"
        "# Isolamento (privacidade — inviolável)\n"
        "Use SOMENTE o contexto deste aluno e o conteúdo pedagógico abaixo. NUNCA "
        "mencione, suponha ou reaproveite dados de outro aluno.\n\n"
        f"# {guardrails.anti_hallucination_rules(sufficient)}"
        f"{rag_block}"
    )


async def respond(user_id: str, message: str, *, language: str = "en", level: str | None = None) -> dict:
    profile = await learning_intel.get_profile(user_id)
    chunks = await rag.search(message, level=level or profile.level, k=4)
    assessment = guardrails.assess(chunks)
    context, sources = rag.build_context(assessment["used"])
    system = build_system_prompt(profile, context, assessment["sufficient"])

    settings = get_settings()
    try:
        reply = await complete(
            system, message, max_tokens=400, temperature=0.2, model=settings.anthropic_model_haiku
        )
    except Exception:  # noqa: BLE001 — never 500 the tutor; degrade to a safe message
        reply = "Desculpa, tive um problema agora. Pode tentar de novo?"

    return {
        "reply": reply.strip(),
        "used_context": assessment["sufficient"],
        "sources": [
            {"topic": c.get("topic"), "level": c.get("level"), "similarity": c.get("similarity")}
            for c in sources
        ],
    }
