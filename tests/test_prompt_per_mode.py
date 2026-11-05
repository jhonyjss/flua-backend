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

# The spec's ceiling ("no máximo metade do tamanho atual", proposed at 7,000 characters in English).
MAX_CHARS = 7000
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


def test_the_language_question_is_asked_once_at_the_opening_not_mid_conversation():
    out = prompt("free_practice", "intermediate")
    assert "Na sua primeira fala, pergunte também, uma vez só" in out.split("# Como começar")[1]
    assert "pergunte" not in out.split("# Idioma")[1].split("#")[0]


def test_legacy_paths_keep_the_old_prompt():
    # a lesson without goalTool (clients older than flueai PR #11) and Spanish stay as they were
    old_lesson = build_tutor_instructions_from_request(
        RealtimeSessionRequest(**lesson(goalTool=False)), None, [],
    )
    assert "# Marcador de avaliação" in old_lesson
    spanish = build_tutor_instructions_from_request(RealtimeSessionRequest(**lesson(language="es")), None, [])
    assert "# Metas da aula (o app conduz — siga à risca)" in spanish
