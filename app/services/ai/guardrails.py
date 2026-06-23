"""Anti-hallucination guardrails for RAG-backed tutor answers (pure)."""

from __future__ import annotations

# A retrieved chunk below this cosine similarity is too weak to rely on.
MIN_SIMILARITY = 0.35


def assess(chunks: list[dict], min_similarity: float = MIN_SIMILARITY) -> dict:
    """Decide whether the retrieved context is strong enough to ground an answer."""
    chunks = chunks or []
    used = [c for c in chunks if float(c.get("similarity") or 0.0) >= min_similarity]
    best = max((float(c.get("similarity") or 0.0) for c in chunks), default=0.0)
    return {
        "sufficient": len(used) > 0,
        "used": used,
        "best_similarity": round(best, 3),
    }


def anti_hallucination_rules(sufficient: bool) -> str:
    """The instruction appended to the system prompt based on context strength."""
    if sufficient:
        return (
            "Regra anti-alucinação: baseie a explicação no CONTEXTO fornecido. "
            "Se algo não estiver no contexto e você não tiver certeza, diga com "
            "honestidade que não tem certeza — NUNCA invente regras, traduções ou exemplos."
        )
    return (
        "Regra anti-alucinação: você NÃO recebeu contexto suficiente para esta "
        "pergunta. NÃO invente regras, traduções ou exemplos. Diga com honestidade "
        "que não tem certeza e ofereça apenas o que sabe com segurança, ou peça que "
        "o aluno reformule a pergunta."
    )
