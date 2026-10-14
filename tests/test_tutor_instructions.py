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


# ── Free practice with a topic chosen by the client (the app's unit theme) ──

TOPIC = "Primeiros contatos — Cumprimentar e se apresentar"
MENU = "praticar uma situação real, revisar vocabulário, tirar dúvidas"


def test_free_practice_with_topic_opens_on_it_instead_of_the_menu():
    out = build_tutor_instructions(
        "beginner", "english-tutor", "", "Jhony", "en", mode="free_practice", topic=TOPIC,
    )
    opening = out.split("# Como começar")[-1]
    assert f"hoje vão praticar {TOPIC}" in opening
    assert "Cumprimente Jhony pelo nome" in opening
    assert MENU not in out
    assert f"O tema de hoje já foi escolhido: {TOPIC}." in out
    # still open practice, never the structured lesson path
    assert "Prática livre" in out
    assert "Avaliação de metas" not in out


def test_free_practice_with_topic_asks_name_first_when_unknown():
    out = build_tutor_instructions(
        "beginner", "english-tutor", "", "", "en", mode="free_practice", topic=TOPIC,
    )
    opening = out.split("# Como começar")[-1]
    assert "Como posso te chamar?" in opening
    assert f"hoje vão praticar {TOPIC}" in opening
    assert MENU not in out


def test_free_practice_spanish_with_topic():
    out = build_tutor_instructions(
        "beginner", "spanish-tutor", "", "Jhony", "es", mode="free_practice", topic="En el café",
    )
    assert "hoje vão praticar En el café" in out.split("# Como começar")[-1]
    assert "apenas conversar em espanhol" not in out


def test_blank_topic_keeps_the_menu():
    out = build_tutor_instructions(
        "beginner", "english-tutor", "", "Jhony", "en", mode="free_practice", topic="   ",
    )
    assert MENU in out
    assert "O tema de hoje já foi escolhido" not in out


def test_topic_is_one_short_line():
    out = build_tutor_instructions(
        "beginner", "english-tutor", "", "Jhony", "en", mode="free_practice",
        topic="Primeiros\ncontatos " + "x" * 300,
    )
    chosen = out.split("O tema de hoje já foi escolhido: ")[1].split(". NÃO ofereça")[0]
    # newline collapsed to a space, then capped at 120 chars: "Primeiros contatos " (19) + 101 x
    assert chosen == "Primeiros contatos " + "x" * 101


def test_topic_is_ignored_in_lesson_mode():
    out = build_tutor_instructions(
        "beginner", "english-tutor", "Aula: To Be", "Jhony", "en", mode="lesson", topic=TOPIC,
    )
    assert TOPIC not in out


# ── Level-based language behavior (advanced immersion / intermediate choice) ──


def test_advanced_is_english_only_immersion():
    out = build_tutor_instructions("advanced", "english-tutor", "Aula", "Jhony", "en")
    assert "imersão total" in out
    assert "EXCLUSIVAMENTE em inglês americano" in out
    assert "FALANDO SÓ EM INGLÊS" in out  # greeting
    # advanced must NOT carry the adaptive "student decides the proportion" rule
    assert "Idioma adaptativo" not in out


def test_intermediate_asks_language_preference():
    out = build_tutor_instructions("intermediate", "english-tutor", "Aula", "Jhony", "en")
    assert "o ALUNO escolhe" in out
    assert "confortável em fazer a aula toda em inglês ou se prefere em português" in out
    # if they choose English-only, immersion kicks in; switching back is allowed
    assert "EXCLUSIVAMENTE em inglês americano (imersão)" in out
    assert "pode TROCAR a qualquer momento" in out


def test_beginner_still_mostly_portuguese():
    out = build_tutor_instructions("beginner", "english-tutor", "Aula", "Jhony", "en")
    assert "90% em português" in out
    assert "imersão total" not in out


def test_advanced_spanish_is_spanish_only():
    out = build_tutor_instructions("advanced", "spanish-tutor", "", "Jhony", "es")
    assert "EXCLUSIVAMENTE em espanhol" in out
