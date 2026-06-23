"""Unit tests for the RAG/guardrails pure helpers (no embeddings / no I/O)."""

from app.schemas.learning_intel import LearningProfile
from app.services.ai import guardrails, rag
from app.services.ai.tutor_respond import build_system_prompt


# ── chunking ─────────────────────────────────────────────────────────────


def test_chunk_short_text_single_chunk():
    assert rag.chunk_text("hello world") == ["hello world"]
    assert rag.chunk_text("   ") == []


def test_chunk_long_text_respects_max_chars():
    paras = "\n".join(f"paragraph number {i} " * 6 for i in range(40))
    chunks = rag.chunk_text(paras, max_chars=300, overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)


def test_chunk_hard_splits_a_huge_paragraph():
    chunks = rag.chunk_text("x" * 2500, max_chars=900, overlap=100)
    assert len(chunks) >= 3
    assert all(len(c) <= 900 for c in chunks)


# ── context building ─────────────────────────────────────────────────────


def test_build_context_numbers_and_caps():
    chunks = [
        {"content": "Phrasal verbs combine a verb + particle.", "topic": "phrasal_verbs", "level": "B1"},
        {"content": "make an effort = fazer um esforço.", "topic": "collocations", "level": "B1"},
    ]
    text, used = rag.build_context(chunks, max_chars=1000)
    assert "[1]" in text and "[2]" in text
    assert "phrasal_verbs" in text
    assert len(used) == 2


def test_build_context_empty():
    assert rag.build_context([]) == ("", [])
    assert rag.build_context([{"content": "   "}]) == ("", [])


# ── guardrails ───────────────────────────────────────────────────────────


def test_assess_filters_weak_chunks():
    chunks = [{"similarity": 0.62}, {"similarity": 0.20}]
    out = guardrails.assess(chunks)
    assert out["sufficient"] is True
    assert len(out["used"]) == 1
    assert out["best_similarity"] == 0.62


def test_assess_insufficient_when_all_weak():
    out = guardrails.assess([{"similarity": 0.1}, {"similarity": 0.2}])
    assert out["sufficient"] is False
    assert out["used"] == []


def test_anti_hallucination_rules_vary_by_sufficiency():
    strong = guardrails.anti_hallucination_rules(True)
    weak = guardrails.anti_hallucination_rules(False)
    assert "CONTEXTO" in strong
    assert "NÃO invente" in weak
    assert "não tem certeza" in weak


# ── system prompt assembly ───────────────────────────────────────────────


def test_build_system_prompt_uses_profile_and_isolation():
    profile = LearningProfile(level="B2", weaknesses=["phrasal_verbs"], learning_goal="C1 for interviews")
    prompt = build_system_prompt(profile, context="[1] phrasal verbs…", sufficient=True)
    assert "B2" in prompt
    assert "phrasal_verbs" in prompt
    assert "C1 for interviews" in prompt
    assert "Isolamento" in prompt
    assert "RAG" in prompt  # context block included
    # no context → still isolated + anti-hallucination, no RAG block
    prompt2 = build_system_prompt(profile, context="", sufficient=False)
    assert "NÃO invente" in prompt2
    assert "Conteúdo pedagógico (RAG" not in prompt2
