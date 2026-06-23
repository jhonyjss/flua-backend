"""Tests for the Flua voice-tutor instructions — focus on student-name handling."""

from app.services.tutor_instructions import build_tutor_instructions


def test_greets_by_first_name_when_provided():
    out = build_tutor_instructions("beginner", "english-tutor", "Aula: Verbo To Be", "João Silva", "en")
    # uses the FIRST name only, greets by it
    assert "Cumprimente João pelo nome" in out
    assert "Silva" not in out.split("# Como começar")[-1]


def test_includes_brazilian_name_care_rules():
    out = build_tutor_instructions("beginner", "english-tutor", "", "Maria", "en")
    assert "# Nome do aluno" in out
    # never anglicize / translate, never use any OTHER name
    assert "americanize" in out.lower()
    assert "NUNCA use, invente ou suponha qualquer outro nome" in out


def test_asks_name_once_when_missing():
    out = build_tutor_instructions("beginner", "english-tutor", "Aula", "", "en")
    assert "Como posso te chamar?" in out
    # only one ask — the greeting instruction tells it to ask and stop
    assert "pare." in out
    # no placeholder leakage
    assert "[nome]" in out  # mentioned only as a FORBIDDEN placeholder, in its rule


def test_spanish_builder_has_name_rules():
    out = build_tutor_instructions("beginner", "spanish-tutor", "", "", "es")
    assert "# Nome do aluno" in out
    # unknown name → forbidden to invent one
    assert "inventar" in out.lower()
    assert "Como posso te chamar?" in out


# ── Free practice mode + clarification ───────────────────────────────────


def test_free_practice_asks_goal_menu_and_drops_lesson_path():
    out = build_tutor_instructions(
        "beginner", "english-tutor", "Free English conversation", "Jhony", "en",
        mode="free_practice",
    )
    # offers the goal menu and waits for the student's choice
    assert "praticar uma situação real, revisar vocabulário, tirar dúvidas" in out
    assert "Prática livre" in out
    # no rigid lesson scaffolding even though a lesson_context string was passed
    assert "Avaliação de metas" not in out
    assert "Marcador de avaliação" not in out


def test_lesson_mode_keeps_structured_path():
    out = build_tutor_instructions(
        "beginner", "english-tutor", "Aula: To Be", "Jhony", "en", mode="lesson",
    )
    assert "Avaliação de metas" in out
    assert "Prática livre (conversa guiada" not in out


def test_clarification_rule_present_in_both_modes():
    msg = "Não consegui entender claramente. Pode repetir, por favor?"
    lesson = build_tutor_instructions("beginner", "english-tutor", "Aula", "Jhony", "en")
    free = build_tutor_instructions("beginner", "english-tutor", "", "Jhony", "en", mode="free_practice")
    es = build_tutor_instructions("beginner", "spanish-tutor", "", "Jhony", "es", mode="free_practice")
    assert msg in lesson
    assert msg in free
    assert msg in es


def test_free_practice_spanish_menu():
    out = build_tutor_instructions(
        "beginner", "spanish-tutor", "", "Jhony", "es", mode="free_practice",
    )
    assert "apenas conversar em espanhol" in out
    assert "Prática livre" in out
