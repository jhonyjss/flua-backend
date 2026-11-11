"""Stage 2c (flueai docs/flua-tutor/02-medir-e-enxugar.md): one English prompt per mode, short and without rules the
mode makes impossible. The fixtures are the eval's (evals/flua/cases.py), the same requests the baseline measured."""
import re

import pytest

from app.schemas.realtime import RealtimeSessionRequest
from app.services.realtime import build_tutor_instructions_from_request
from evals.flua.cases import TOPIC, free, guided, lesson

MODES = {
    "lesson": lambda level: lesson(level=level),
    "guided_lesson": lambda level: guided(level=level),
    "free_practice": lambda level: free(level=level, topic=TOPIC,
                                        reviewPhrases=[{"english": "Good morning", "portuguese": "Bom dia"}]),
}
MEMORY = [{"said": "I am agree", "natural": "I agree", "tip": "agree já é verbo, sem am"}]
# Real app plans carry a grammar point (the app's docs/gramatica-spec.md); the eval's plan doesn't.
GRAMMAR = {
    "name": "Verbo to be para se apresentar",
    "rule": "Para dizer quem você é, use I am + nome; para dizer o nome, My name is + nome.",
    "forms": [
        {"label": "afirmativa", "english": "I am Ana.", "portuguese": "Eu sou a Ana."},
        {"label": "nome", "english": "My name is Ana.", "portuguese": "Meu nome é Ana."},
        {"label": "contração", "english": "I'm Ana.", "portuguese": "Sou a Ana."},
    ],
    "contrast": "Em português dá para dizer só \"Sou a Ana\"; em inglês o I é obrigatório.",
    "mistake": {"wrong": "Am Ana.", "right": "I am Ana.", "why": "o sujeito não cai em inglês"},
    "recap": "I am + nome; My name is + nome.",
}

# The spec's ceiling ("no máximo metade do tamanho atual", proposed at 7,000 characters in English), measured on the
# eval's requests. A real guided plan adds its grammar point, which is lesson data, not instructions: for that the
# ceiling is the top of the research's 6–8k range (spec changed with 2c's review, flueai 02-medir-e-enxugar.md).
MAX_CHARS = 7000
MAX_CHARS_WITH_GRAMMAR = 8000
# "NUNCA" kept for the few rules that can't bend (other languages, other names, advancing alone).
MAX_NUNCA = 5
# Rules with no input in these modes: the client drives the turn (no silence to fill, no barge-in), the labels
# are never sent, the tool's answer is the only correction.
DEAD_RULES = ["Não preencha silêncios", "Se for interrompida", "repetition mode", "EXACT_MATCH",
              "PARTIALLY_CORRECT", "Não pule etapas", "PRECEDÊNCIA", "# Correção", "Podemos continuar?"]


def prompt(mode: str, level: str = "beginner", mistakes: list | None = None) -> str:
    req = RealtimeSessionRequest(**MODES[mode](level))
    return build_tutor_instructions_from_request(req, None, mistakes or [])


CASES = [(mode, level) for mode in MODES for level in ("beginner", "intermediate", "advanced")]


@pytest.mark.parametrize(("mode", "level"), CASES, ids=[f"{m}-{lv}" for m, lv in CASES])
def test_each_mode_fits_the_ceiling_with_few_absolute_rules(mode, level):
    out = prompt(mode, level, MEMORY)
    assert len(out) <= MAX_CHARS
    assert len(re.findall(r"\bNUNCA\b", out)) <= MAX_NUNCA


def test_a_guided_lesson_with_its_grammar_point_fits_the_ceiling():
    plan = {**guided()["plan"], "grammar": GRAMMAR}
    out = build_tutor_instructions_from_request(RealtimeSessionRequest(**guided(plan=plan)), None, [])
    assert "# Gramática da aula: Verbo to be para se apresentar" in out
    assert len(out) <= MAX_CHARS_WITH_GRAMMAR


@pytest.mark.parametrize("mode", list(MODES))
def test_no_rule_without_input_in_the_mode(mode):
    out = prompt(mode)
    assert [rule for rule in DEAD_RULES if rule in out] == []


@pytest.mark.parametrize("mode", list(MODES))
def test_each_rule_is_said_once(mode):
    out = prompt(mode)
    assert out.count("nunca outra língua") == 1
    assert out.count("NUNCA use, invente ou suponha qualquer outro nome") == 1
    assert out.count("Não consegui entender claramente. Pode repetir, por favor?") == 1


@pytest.mark.parametrize("mode", list(MODES))
def test_sections_follow_the_realtime_skeleton(mode):
    headings = [line for line in prompt(mode).splitlines() if line.startswith("# ")]
    shared = ["# Personalidade e tom", "# Idioma", "# Nome do aluno", "# Precisão", "# Áudio pouco claro",
              "# Sotaque e pronúncia"]
    assert headings[:len(shared)] == shared
    assert headings[-1] == "# Como começar"


def test_the_tool_modes_correct_only_through_the_tool_and_free_practice_by_recast():
    for mode, tool in (("lesson", "registrar_meta"), ("guided_lesson", "registrar_resultado")):
        out = prompt(mode)
        assert f"A resposta de {tool} é o próximo passo" in out
        assert "Corrija por RECAST" not in out
    out = prompt("free_practice")
    assert "Corrija por RECAST" in out
    assert "registrar_" not in out


def language_section(out: str) -> str:
    return out.split("# Idioma\n")[1].split("\n# ")[0]


@pytest.mark.parametrize(("mode", "level"), CASES, ids=[f"{m}-{lv}" for m, lv in CASES])
def test_english_is_the_default_at_every_level_and_portuguese_comes_on_request(mode, level):
    # Spec changed (flueai docs/flua-tutor/04-professor-por-voz.md, D2): the intermediate opening no longer asks
    # which language, and the beginner no longer hears mostly Portuguese.
    out = prompt(mode, level)
    section = language_section(out)
    assert "Fale inglês americano natural em qualquer nível" in section
    assert 'Português só quando ele pedir ("explica em português", "não entendi")' in section
    assert "prefere tudo em inglês" not in out
    assert "Iniciante: fale em português" not in out


def test_the_profile_explanation_language_no_longer_changes_the_english_prompt():
    for mode in MODES:
        pt = build_tutor_instructions_from_request(RealtimeSessionRequest(**MODES[mode]("beginner")), None, [])
        en = build_tutor_instructions_from_request(
            RealtimeSessionRequest(**MODES[mode]("beginner"), explanationLanguage="en"), None, [],
        )
        assert pt == en


def test_portuguese_content_is_only_what_would_give_the_answer_away():
    assert "Fica em português a tradução do modelo, nunca a resposta do aluno:" in prompt("lesson")
    assert 'Fica em português a tradução do modelo e o pedido "sua vez":' in prompt("guided_lesson")
    assert 'Fica em português a pergunta "como se diz…?" do aquecimento:' in prompt("free_practice")


@pytest.mark.parametrize("mode", list(MODES))
def test_every_mode_speaks_in_short_turns_and_slows_down_on_request(mode):
    tone = prompt(mode).split("# Personalidade e tom\n")[1].split("\n# ")[0]
    assert "no máximo 4 frases curtas, normalmente 2 ou 3" in tone
    assert "se perguntar, uma pergunta só" in tone
    assert 'Pediu "mais devagar"' in tone
    assert "nem toda resposta pede elogio" in tone


def test_free_practice_offers_the_three_modes_and_closes_with_three_learnings():
    out = prompt("free_practice")
    modes = out.split("# Modos")[1].split("\n# ")[0]
    for name in ("- Conversa livre:", "- Correção guiada", "- Listening e shadowing"):
        assert name in modes
    assert "no máximo 2 pontos importantes" in modes
    assert "não após toda correção" in modes
    assert "uma frase curta para cada um de três aprendizados da conversa" in modes
    # vocabulary growth and slang belong to the open conversation
    assert "até C1/C2" in out and "alternativa profissional" in out
    for mode in ("lesson", "guided_lesson"):
        assert "C1/C2" not in prompt(mode) and "# Modos" not in prompt(mode)


def test_turn_taking_rules_only_where_the_learner_can_pause_or_interrupt_her():
    # free practice is server-driven (conversational): she can be interrupted and must wait out hesitations; the
    # lessons are client-driven, so these rules would have no input there (2c principle).
    assert 'Nada de "mhm"; se ele falar enquanto você fala, pare e responda a ele.' in prompt("free_practice")
    for mode in ("lesson", "guided_lesson"):
        assert "mhm" not in prompt(mode)


def test_where_no_tool_corrects_a_stuck_learner_gets_the_help_ladder():
    for mode in ("free_practice", "lesson"):
        assert "primeira palavra" in prompt(mode) and "metade" in prompt(mode)
    assert "blocos prontos" in prompt("free_practice")


def test_the_lesson_keeps_the_profile_goals():
    req = RealtimeSessionRequest(**lesson(learningGoals=["work"]))
    out = build_tutor_instructions_from_request(req, None, [])
    assert "# Foco do aluno" in out and "trabalho (reuniões" in out


def test_legacy_paths_keep_the_old_prompt():
    # a lesson without goalTool (clients older than flueai PR #11) and Spanish stay as they were
    old_lesson = build_tutor_instructions_from_request(
        RealtimeSessionRequest(**lesson(goalTool=False)), None, [],
    )
    assert "# Marcador de avaliação" in old_lesson
    spanish = build_tutor_instructions_from_request(RealtimeSessionRequest(**lesson(language="es")), None, [])
    assert "# Metas da aula (o app conduz — siga à risca)" in spanish


def opening(out: str) -> str:
    return out.split("# Como começar\n")[1]


def test_free_practice_openings_name_their_two_sentences():
    # In English the plain openings ran to 4 sentences (04-professor-por-voz.md): each one says what its 2 are.
    with_topic = opening(prompt("free_practice"))
    no_warmup = build_tutor_instructions_from_request(RealtimeSessionRequest(**free(topic=TOPIC)), None, [])
    assert "Cumprimente Ana pelo nome em 2 frases: o cumprimento com o tema de hoje" in opening(no_warmup)
    no_topic = build_tutor_instructions_from_request(RealtimeSessionRequest(**free()), None, [])
    assert ("Cumprimente Ana pelo nome em 2 frases: o cumprimento e a pergunta sobre o que ele quer praticar hoje "
            "(uma situação real, vocabulário, uma dúvida ou só conversar)") in opening(no_topic)
    # the warmup's greeting says none of its phrases (an English "good morning" gave the answer away)
    assert 'Cumprimente só com "Hi, Ana!" (nenhuma frase do aquecimento)' in with_topic


def test_without_a_name_the_warmup_asks_the_name_and_never_greets_with_one():
    req = RealtimeSessionRequest(**free(topic=TOPIC, studentName="",
                                        reviewPhrases=[{"english": "Good morning", "portuguese": "Bom dia"}]))
    first = opening(build_tutor_instructions_from_request(req, None, []))
    assert first.startswith('Você fala primeiro, imediatamente ao conectar. Cumprimente com "Hi!", pergunte '
                            '"Como posso te chamar?" e pare.')
    assert "o nome (" not in first and '"Hi, ' not in first


def test_a_guided_opening_with_grammar_keeps_the_grammar_class_uncapped():
    # Real plans carry a grammar point: the opening is greeting + grammar class (≤4) + item 1, so no total cap
    # may contradict it.
    plan = {**guided()["plan"], "grammar": GRAMMAR}
    first = opening(build_tutor_instructions_from_request(RealtimeSessionRequest(**guided(plan=plan)), None, []))
    assert "dê a aula de gramática (veja # Gramática da aula) em até 4 frases curtas, em inglês simples" in first
    assert "no máximo" not in first
    assert 'na mesma frase diga que hoje ele vai aprender a se apresentar (ex.: "Hi Ana, today you\'ll learn to …!")' in first
