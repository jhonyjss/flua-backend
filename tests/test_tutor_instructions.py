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
    # Spec changed (flueai docs/flua-tutor/02-medir-e-enxugar.md, 2c): one prompt per mode, new wording.
    # offers the goal menu and waits for the student's choice
    assert MENU in out.split("# Como começar")[-1]
    assert "# Como a conversa funciona (prática livre" in out
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
MENU = "uma situação real, vocabulário, uma dúvida ou só conversar"


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
    assert "# Como a conversa funciona (prática livre" in out
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


GUIDED_FLOW = "# Como a aula funciona (o roteiro é do app)"


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
    # Spec changed (flueai docs/flua-tutor/02-medir-e-enxugar.md, 2c): one prompt per mode, new wording.
    # the lesson's elicitation rules (hint → try again) stay in the lesson, out of free practice
    assert "Em aula estruturada, se errar pela 1ª vez naquela frase" in casual
    assert "Em aula estruturada" not in free


def test_english_prompt_anticipates_brazilian_l1_errors():
    out = _lesson()
    assert "# Erros típicos de brasileiro" in out
    assert '"I have 30 years" → "I\'m 30"' in out
    assert "actually = na verdade" in out
    assert "# Portunhol" not in out


def test_guided_tool_result_overrides_the_generic_correction_rules():
    # Spec changed (flueai docs/flua-tutor/02-medir-e-enxugar.md, 2c): one prompt per mode, new wording.
    out = _guided()
    # no generic correction block to override: the tool's answer is the only correction
    assert "# Correção" not in out and "PRECEDÊNCIA" not in out
    assert "Não dê pista, não corrija nem peça nova tentativa por conta própria." in out
    assert "# Reconhecimento de acerto" not in out
    assert 'sua vez (etapa "sozinho")' in out


def test_guided_acceptance_counts_contractions_and_flags_missing_words():
    out = _guided()
    assert "Contração e forma plena valem igual (I'm = I am" in out
    assert "Sujeito, artigo ou preposição faltando NÃO é detalhe: é parcial" in out
    assert "work-ed" not in out.split(GUIDED_FLOW)[1]  # the accent list sits in its own section


def test_guided_acceptance_judges_what_she_heard_and_forgives_the_accent():
    # "Hello Ana" said with a Brazilian accent was judged wrong: she hears audio, not a transcript,
    # and tree/three, sheep/ship (pronunciation pairs) taught her to mark accent as a different word.
    block = _guided().split(GUIDED_FLOW)[1]
    assert "pelo que você OUVIU" in block
    assert "transcrição mostra" not in block
    assert "tree/three" not in block and "sheep/ship" not in block
    assert 'Sotaque é a mesma palavra: hello dito "rélou" e Ana dita "Âna" são as mesmas palavras.' in block
    assert 'Pausa, entonação, vírgula e pontuação não contam (ex.: "hello Ana", sem a pausa da vírgula, vale "Hello, Ana!").' in block
    assert "Na etapa repetir, na dúvida entre correto e parcial, é correto." in block


def test_guided_acceptance_still_catches_a_real_word_swap():
    # accent tolerance must not let a word with another meaning pass. Spec changed (flueai
    # docs/flua-tutor/01-fiacao.md §3): the example was leave/live, the vowel pair a Brazilian accent
    # merges, so it taught Flua to fail the accent; the swap examples are now words no accent confuses.
    block = _guided().split(GUIDED_FLOW)[1]
    assert "OUTRA palavra é só quando você ouviu claramente uma palavra diferente, com outro sentido" in block
    assert '"dog" no lugar de "cat"' in block
    assert '"leave"' not in block and '"live"' not in block
    assert "na dúvida entre sotaque e outra palavra, é sotaque" in block
    assert "se você reconhece a palavra, ela está certa" not in block


def test_hard_sounds_for_brazilians_are_accent_never_a_wrong_word():
    out = _lesson()
    assert 'vogal curta e longa ("ship" × "sheep")' in out
    assert "Esses sons são sotaque: numa avaliação, nunca contam como palavra errada." in out


# ── Site lesson with client-owned goals (goalTool) ───────────────────────


def _goal_lesson(language="en"):
    return build_tutor_instructions(
        "beginner", "english-tutor", "Metas desta aula:\n1. Cumprimentar\n2. Dizer o nome", "Jhony", language,
        mode="lesson", goal_tool=True,
    )


def test_goal_tool_lesson_is_driven_by_registrar_meta_not_a_spoken_marker():
    # Spec changed (flueai docs/flua-tutor/02-medir-e-enxugar.md, 2c): English has its own lesson prompt.
    english = _goal_lesson("en")
    assert "# Como a aula funciona (o app conduz o progresso)" in english
    assert "o app pede registrar_meta com a meta atual" in english
    assert "faça tudo o que ela pedir, na ordem, numa única fala" in english
    assert "NUNCA avance nem pule meta por conta própria" in english
    spanish = _goal_lesson("es")
    assert "# Metas da aula (o app conduz — siga à risca)" in spanish
    assert "a instrução que volta de registrar_meta tem PRECEDÊNCIA" in spanish
    for out in (english, spanish):
        assert "o app" in out
        # the marker flow it replaces is gone
        assert "# Marcador de avaliação" not in out
        assert "# Ao concluir cada tarefa" not in out
        assert "Podemos continuar?" not in out
        assert "UMA ÚNICA VEZ por meta" not in out


def test_goal_tool_lesson_judges_by_what_she_heard_with_the_shared_rules():
    # Spec changed (flueai docs/flua-tutor/02-medir-e-enxugar.md, 2c): one prompt per mode, new wording.
    out = _goal_lesson()
    block = out.split("# Como a aula funciona (o app conduz o progresso)")[1]
    assert "pelo que você OUVIU" in block
    assert 'Sotaque é a mesma palavra: hello dito "rélou"' in block
    assert '"dog" no lugar de "cat"' in block
    assert "fora_do_roteiro: dúvida, pedido de ajuda, fala só em português" in block
    assert "nunca escreva a frase-modelo no lugar do que ele disse" in block
    # the guided lesson's own steps don't leak into the site lesson
    assert "etapa repetir" not in block and "registrar_resultado" not in block


def test_goal_tool_keeps_the_lesson_and_closing_guidance():
    # Spec changed (flueai docs/flua-tutor/02-medir-e-enxugar.md, 2c): one prompt per mode, new wording.
    out = _goal_lesson()
    assert "# Aula de hoje" in out
    # the marker flow's guard against a goodbye with goals still pending survives the switch to the tool
    assert "Antes de o app dizer que as metas terminaram, não se despeça" in out
    assert '"Ainda temos mais para praticar — vamos continuar?"' in out
    assert "Metas terminadas: siga praticando o mesmo foco" in out
    assert "1 ponto forte, 1 a melhorar e uma despedida carinhosa" in out


def test_goal_tool_needs_a_lesson():
    # a lesson without context has no goals to drive: the casual conversation stays as it was
    out = build_tutor_instructions("beginner", "english-tutor", "", "Jhony", "en", mode="lesson", goal_tool=True)
    assert "# Metas da aula" not in out
    assert "# Conversa livre" in out


# ── Free practice: the client's context is a theme, not a syllabus ───────


def test_free_practice_context_is_a_theme_not_steps():
    for language, scenario in (("en", "english-tutor"), ("es", "spanish-tutor")):
        out = build_tutor_instructions(
            "beginner", scenario, "Tema: Primeiros contatos. Frases que ele conhece: Hi! | I'm Ana.", "Jhony",
            language, mode="free_practice",
        )
        assert "# Tema e contexto da conversa\nTema: Primeiros contatos." in out
        assert "Não é uma aula com etapas: siga o rumo que o aluno der à conversa." in out
        assert "# Aula de hoje" not in out
        assert "Não pule etapas" not in out


def test_free_practice_does_not_end_every_turn_on_a_question():
    out = build_tutor_instructions("beginner", "english-tutor", "", "Jhony", "en", mode="free_practice")
    # Spec changed (flueai docs/flua-tutor/02-medir-e-enxugar.md, 2c): one prompt per mode, new wording.
    assert "Conversa não é interrogatório: depois de duas falas suas com pergunta, a próxima não tem pergunta" in out


def test_guided_heard_keeps_the_learners_actual_words():
    # o_que_ouviu feeds the mistakes Flua remembers; the model phrase written there erases the miss
    block = _guided().split(GUIDED_FLOW)[1]
    assert "se faltou ou trocou palavra, deixe faltando ou trocada" in block
    assert "nunca escreva a frase-modelo no lugar do que ele disse" in block
    assert "com a grafia normal, sem imitar o sotaque" not in block


def test_guided_teaching_gives_real_context_and_ends_on_the_phrase_to_repeat():
    # The learner starts repeating as soon as the phrase is heard; anything after it talks over them.
    # Spec changed (flueai docs/flua-tutor/02-medir-e-enxugar.md, 2c): one prompt per mode, new wording.
    block = _guided().split(GUIDED_FLOW)[1]
    assert '1 de contexto real (ex.: "De manhã, os americanos costumam cumprimentar com Good morning.")' in block
    assert "a frase em inglês com a tradução (e a nota, se ajudar)" in block
    assert 'o convite com a frase de novo (ex.: "Vamos praticar juntos — repete comigo: Good morning!")' in block
    assert "Sem pergunta: a frase-modelo é a última coisa da fala." in block
    assert "Vamos praticar juntos?" not in block
    assert "em no máximo 2 frases curtas e peça para o aluno repetir" not in block


def test_guided_feedback_sounds_like_a_teacher_not_a_grader():
    # Spec changed (flueai docs/flua-tutor/02-medir-e-enxugar.md, 2c): one prompt per mode, new wording.
    out = _guided()
    block = out.split(GUIDED_FLOW)[1]
    assert 'nunca diga "errado", "incorreto" nem comece com "não"' in block
    assert "Vamos juntos de novo?" in block
    assert "Encerramento: só o que a instrução pedir, sem pergunta." in block
    assert 'fora_do_roteiro, "tentativa 1 de 2")' in out.split("# Nunca diga")[1]
    assert "feedback curto e o próximo pedido" not in block


def test_spanish_guided_lesson_teaches_with_spanish_examples():
    block = build_tutor_instructions(
        "beginner", "spanish-tutor", "", "Jhony", "es", mode="guided_lesson", guided=GUIDED,
    ).split("# Aula guiada")[1]
    assert "repete comigo: ¡Buenos días!" in block
    assert 'Sotaque é a mesma palavra: "buenos" dito "buênos" e "días" dito "djías" são as mesmas palavras.' in block
    # spec changed (flueai docs/flua-tutor/01-fiacao.md §3): perro/pero is the r/rr pair a Brazilian
    # accent merges, so the swap example is now one no accent confuses
    assert '"gato" no lugar de "perro"' in block
    assert '"pero"' not in block
    assert "Good morning" not in block and "Hello, Ana" not in block and "rélou" not in block


def test_guided_lesson_block_refuses_a_language_without_examples():
    # a silent fallback would teach a French lesson with English examples
    import pytest
    from app.services.tutor_instructions import _guided_lesson_block

    with pytest.raises(KeyError):
        _guided_lesson_block("francês")


def test_lesson_mode_judges_by_what_she_heard_not_a_transcript():
    for language in ("en", "es"):
        out = _lesson(language)
        assert "Use a transcrição" not in out
        assert "Julgue pelo que você ouviu (você recebe o áudio, não uma transcrição)" in out


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
