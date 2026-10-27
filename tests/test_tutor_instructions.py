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


GUIDED = {
    "title": "Apresentações",
    "skill": "se apresentar",
    "items": [
        {"id": "c-i-am", "english": "I am Ana.", "portuguese": "Eu sou Ana.", "note": "I sempre vem com am."},
        {"id": "c-my-name-is", "english": "My name is Ana.", "portuguese": "Meu nome é Ana.",
         "note": "My name\nsempre vem com is.", "cue": "Diga o seu nome para a Flua.",
         "accepts": ["My name is <nome>.", "I am <nome>."]},
    ],
}


def _guided(name="Jhony", resume=0):
    return build_tutor_instructions(
        "beginner", "english-tutor", "", name, "en", mode="guided_lesson", guided=GUIDED, resume_from_item=resume,
    )


def test_guided_lesson_opens_with_the_lesson_proposal_then_teaches_item_one():
    opening = _guided().split("# Como começar")[-1]
    assert "Cumprimente Jhony pelo nome" in opening
    assert "hoje ele vai aprender a se apresentar" in opening
    assert "são 2 itens" in opening
    assert "ensine o item 1 (c-i-am)" in opening
    assert MENU not in _guided()


def test_guided_lesson_lists_every_item_on_one_line_with_its_cue():
    out = _guided()
    assert '1. id=c-i-am | frase: "I am Ana." | tradução: "Eu sou Ana." | nota: I sempre vem com am.' in out
    assert "nota: My name sempre vem com is." in out  # newline collapsed
    assert 'sua vez: "Diga o seu nome para a Flua." | aceitas: My name is <nome>. / I am <nome>.' in out
    # an item without a cue lets Flua write the "sua vez" request herself
    assert "sua vez: (crie um pedido curto em português" in out.split("2. id=")[0]


def test_guided_lesson_is_driven_by_the_tool_not_by_flua():
    out = _guided()
    assert "registrar_resultado" in out
    assert "NUNCA avance de item ou de etapa por conta própria" in out
    # the structured-lesson scaffolding (spoken "Correct!" marker) and the free-practice menu stay out
    assert "Marcador de avaliação" not in out
    assert "Prática livre" not in out


def test_guided_lesson_resume_skips_the_opening():
    opening = _guided(resume=1).split("# Como começar")[-1]
    assert "Vamos continuar de onde paramos" in opening
    assert "ensine o item 2 (c-my-name-is)" in opening
    assert "hoje ele vai aprender" not in opening


def test_guided_lesson_asks_the_name_first_when_unknown():
    opening = _guided(name="").split("# Como começar")[-1]
    assert "Como posso te chamar?" in opening
    assert "ensine o item 1 (c-i-am)" in opening


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


# ── Grammar class in the guided lesson (app docs/gramatica-spec.md) ──

GRAMMAR = {
    "name": "Verbo to be: I am",
    "rule": "Em inglês, ser e estar são um verbo só: to be.\nCom I usamos am.",
    "forms": [
        {"label": "Afirmativa", "english": "I am Ana.", "portuguese": "Eu sou a Ana."},
        {"label": "Contração", "english": "I'm Ana."},
    ],
    "contrast": "Em português dizemos só “Sou Ana”; em inglês o I é obrigatório.",
    "mistake": {"wrong": "Am Ana.", "right": "I am Ana.", "why": "O sujeito I não pode faltar."},
    "recap": "Com I, o verbo to be é am.",
}


def _guided_with_grammar(resume=0):
    return build_tutor_instructions(
        "beginner", "english-tutor", "", "Jhony", "en", mode="guided_lesson",
        guided={**GUIDED, "grammar": GRAMMAR}, resume_from_item=resume,
    )


def test_guided_plan_carries_the_grammar_point_one_line_per_field():
    out = _guided_with_grammar()
    assert "# Gramática da aula: Verbo to be: I am" in out
    assert "Regra: Em inglês, ser e estar são um verbo só: to be. Com I usamos am." in out  # newline collapsed
    assert 'Formas: Afirmativa: "I am Ana." (Eu sou a Ana.) | Contração: "I\'m Ana."' in out
    assert "Português × inglês: Em português dizemos só “Sou Ana”; em inglês o I é obrigatório." in out
    assert 'Erro comum: "Am Ana." → "I am Ana." (O sujeito I não pode faltar.)' in out
    assert "Resumo para o fim: Com I, o verbo to be é am." in out


def test_guided_lesson_gives_the_grammar_class_before_teaching_item_one():
    opening = _guided_with_grammar().split("# Como começar")[-1]
    grammar_class = opening.index("dê a aula de gramática")
    assert grammar_class < opening.index("ensine o item 1 (c-i-am)")
    assert opening.index("hoje ele vai aprender a se apresentar") < grammar_class


def test_resuming_a_lesson_skips_the_grammar_class():
    opening = _guided_with_grammar(resume=1).split("# Como começar")[-1]
    assert "aula de gramática" not in opening
    assert "ensine o item 2 (c-my-name-is)" in opening


def test_a_plan_without_grammar_has_no_grammar_class():
    out = _guided()
    assert "Gramática da aula" not in out
    assert "aula de gramática" not in out


# ── Teaching methodology (pedagogy review) ───────────────────────────────


def _lesson(language="en"):
    return build_tutor_instructions("beginner", "english-tutor", "Aula: To Be", "Jhony", language, mode="lesson")


def test_lesson_second_miss_ends_in_a_repetition_that_completes_the_goal_in_order():
    out = _lesson()
    # the client completes the next pending goal on each marker, so goals finish in order — never skipped
    assert "peça para ele só repeti-la UMA vez" in out
    assert "Se a repetição sair com as palavras certas, a meta está concluída" in out
    assert "nunca pule para a próxima meta sem concluir a atual" in out
    assert "SIGA para a próxima meta" not in out
    assert "SEM o marcador" not in out


def test_lesson_marker_fires_once_per_goal_never_on_variations():
    en = _lesson()
    es = _lesson("es")
    assert 'Use "Correct!" ou "Correto!" UMA ÚNICA VEZ por meta' in en
    assert 'Use "¡Correcto!" ou "Correto!" UMA ÚNICA VEZ por meta' in es
    for out in (en, es):
        assert "NUNCA comece com o marcador ao responder a uma variação" in out
    assert "(a resposta à variação NÃO leva o marcador)" in en


def test_lesson_asks_for_doubts_only_after_a_miss_or_every_three_goals():
    out = _lesson()
    assert "Pergunte se há dúvida só depois de uma meta que teve erro, ou a cada 3 metas." in out
    assert "se ele tem alguma dúvida sobre o que acabaram de praticar" not in out


def test_conversation_corrects_by_recast_instead_of_stopping_the_talk():
    free = build_tutor_instructions("beginner", "english-tutor", "", "Jhony", "en", mode="free_practice")
    casual = build_tutor_instructions("beginner", "english-tutor", "", "Jhony", "en", mode="lesson")
    es = build_tutor_instructions("beginner", "spanish-tutor", "", "Jhony", "es", mode="free_practice")
    for out in (free, casual, es):
        assert "Corrija por RECAST" in out
    # each language recasts with its own example
    assert "I'm 30 — a gente diz I'm" in free and "I'm 30 — a gente diz I'm" in casual
    assert "Me gusta mucho — a gente diz mucho, não muy" in es
    assert "I'm 30" not in es
    # the elicitation rule (hint → try again) is scoped to the structured lesson
    assert "Em aula estruturada, se errar pela 1ª vez naquela frase" in free
    assert "Em aula estruturada, se o mesmo erro repetir" in free


def test_english_prompt_anticipates_brazilian_l1_errors():
    out = _lesson()
    assert "# Erros típicos de brasileiro" in out
    assert '"I have 30 years" → "I\'m 30"' in out
    assert "actually = na verdade" in out
    assert "# Portunhol" not in out


def test_guided_tool_result_overrides_the_generic_correction_rules():
    out = _guided()
    assert 'registrar_resultado tem PRECEDÊNCIA sobre "# Correção" e os degraus de ajuda.' in out
    assert "# Reconhecimento de acerto" not in out  # no reference to a section the guided prompt lacks
    assert 'sua vez (etapa "sozinho" em registrar_resultado)' in out


def test_guided_acceptance_counts_contractions_and_flags_missing_words():
    out = _guided()
    assert "Contração e forma plena valem igual (I'm = I am" in out
    assert "Sujeito, artigo ou preposição faltando NÃO é detalhe: é parcial" in out
    assert "Se a transcrição mostra OUTRA palavra (tree/three, sheep/ship)" in out
    assert "Sotaque, ritmo e pronúncia NÃO contam enquanto a transcrição mostrar as palavras certas." in out
    assert "work-ed" not in out.split("# Aula guiada")[1]


def test_spanish_guided_lesson_runs_the_scene_in_spanish():
    out = build_tutor_instructions(
        "beginner", "spanish-tutor", "", "Jhony", "es", mode="guided_lesson", guided=GUIDED,
    )
    block = out.split("# Aula guiada")[1]
    assert "você faz um personagem e fala em espanhol" in block
    assert "diga a frase em espanhol" in block
    assert "em inglês" not in block
    assert '"la viaje" → "el viaje"' in block


def test_spanish_prompt_has_turn_rules_correction_and_portunhol():
    out = _lesson("es")
    assert "# Como conversar" in out
    assert "no máximo UM erro por turno" in out
    assert "# Portunhol" in out
    assert "embarazada = grávida" in out
    assert "Sanduíche: toda frase nova em espanhol" in out
    assert "# Erros típicos de brasileiro" not in out
