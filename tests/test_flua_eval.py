"""The Flua eval tooling (evals/flua): case validity, objective checks, the client steps it sends to the
Realtime API (faked at the WebSocket) and the baseline comparison."""
import asyncio
import json
import re
from contextlib import asynccontextmanager

import httpx
import pytest
from websockets.exceptions import ConnectionClosedError

from evals.flua import __main__ as cli
from evals.flua import cases as C
from evals.flua.checks import check_reply, check_tool, sentences
from evals.flua.judge import (
    DEFAULT_JUDGE_MODEL,
    failures_from_verdict,
    judge,
    judge_model,
)
from evals.flua.runner import build_session, regressions, run_case
from evals.flua.session import Reply, TextSession, ToolCall, text_session
from evals.flua.usage import Tokens, Usage

CASE = {case["id"]: case for case in C.CASES}


class FakeRealtime:
    """The Realtime API's side of the WebSocket: answers session.update and each response.create with the next
    scripted output (a list of output items, or "error")."""

    def __init__(self, script: list, drop_at_response: bool = False):
        self.drop_at_response = drop_at_response
        self.script = list(script)
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.inbox.put_nowait(json.dumps({"type": "session.created"}))

    async def send(self, message: str) -> None:
        event = json.loads(message)
        self.sent.append(event)
        if event["type"] == "session.update":
            await self.inbox.put(json.dumps({"type": "session.updated"}))
        elif event["type"] == "response.create":
            if self.drop_at_response:
                raise ConnectionClosedError(None, None)
            output = self.script.pop(0)
            if output == "error":
                await self.inbox.put(json.dumps({"type": "error", "error": {"message": "boom"}}))
            else:
                await self.inbox.put(json.dumps(
                    {"type": "response.done", "response": {"status": "completed", "output": output}},
                ))

    async def recv(self) -> str:
        return await self.inbox.get()


def say(text: str) -> list[dict]:
    return [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]


def calls(name: str, **args) -> list[dict]:
    return [{"type": "function_call", "call_id": "call_1", "name": name, "arguments": json.dumps(args)}]


def fake_connect(script: list, **fake_options):
    fakes: list[FakeRealtime] = []

    @asynccontextmanager
    async def connect(model: str):
        fake = FakeRealtime(script, **fake_options)
        fakes.append(fake)
        yield TextSession(fake)

    return connect, fakes


def judge_answers(text: str, status: int = 200, state: str = "completed") -> httpx.Response:
    """The OpenAI Responses API's answer carrying the judge's text."""
    if status != 200:
        return httpx.Response(status, json={"error": {"message": text}})
    return httpx.Response(200, json={
        "status": state,
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
        "usage": {"input_tokens": 900, "output_tokens": 120},
    })


def all_passed_judge(mock_transport, seen: list | None = None):
    """The judge model, at the HTTP boundary, passing every criterion it is given."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        if seen is not None:
            seen.append(body)
        message = body["input"][1]["content"]
        criteria = len(re.findall(r"(?m)^\d+\. ", message.split("Critérios:")[1]))
        verdict = {"criterios": [{"n": n, "passou": True, "trecho": "ok"} for n in range(1, criteria + 1)]}
        return judge_answers(json.dumps(verdict))

    mock_transport(handler)


# ── The cases themselves ─────────────────────────────────────────────────────

def test_cases_have_unique_ids_and_known_categories():
    ids = [case["id"] for case in C.CASES]
    assert len(ids) == len(set(ids))
    assert {case["category"] for case in C.CASES} == {
        "julgamento", "resposta à ferramenta", "prática livre", "abertura",
    }


@pytest.mark.parametrize("case", C.CASES, ids=lambda case: case["id"])
def test_every_case_builds_the_production_session_and_names_its_tool(case):
    _, config = build_session(case)
    tools = {tool["name"] for tool in config.get("tools", [])}
    for step in case["steps"]:
        if "evaluate" in step:
            assert step["tool"] in tools
    for entry in case.get("history", []):
        if entry[0] == "call":
            assert entry[1] in tools


def test_lesson_cases_run_with_the_goal_tool_and_free_practice_without_tools():
    _, lesson = build_session(CASE["aula-sim"])
    _, practice = build_session(CASE["livre-recast"])
    assert [tool["name"] for tool in lesson["tools"]] == ["registrar_meta"]
    assert "tools" not in practice


def test_text_session_keeps_instructions_and_tools_without_audio_or_model():
    _, config = build_session(CASE["aula-sim"])
    session = text_session(config)
    assert session["output_modalities"] == ["text"]
    assert "audio" not in session and "model" not in session
    assert session["instructions"] == config["instructions"]
    assert session["tools"] == config["tools"]


# ── Objective checks ─────────────────────────────────────────────────────────

def test_sentences_skip_one_word_interjections_and_keep_the_sandwich_whole():
    assert sentences("Isso! Esse I am Ana saiu ótimo. I'm from Brazil — eu sou do Brasil — I'm from Brazil.") == [
        "Esse I am Ana saiu ótimo.", "I'm from Brazil — eu sou do Brasil — I'm from Brazil.",
    ]
    assert sentences('Vamos começar: "Hi, Ana! — Oi, Ana! — Hi, Ana!"  \nAgora, repete comigo.') == [
        'Vamos começar: "Hi, Ana! — Oi, Ana! — Hi, Ana!"', "Agora, repete comigo.",
    ]


def test_reply_check_catches_labels_spanish_placeholders_and_length():
    reply = Reply("Parcial! Muy bien, [nome]. Tente de novo. Mais uma vez agora. Registrar_meta, por favor.")
    assert check_reply(reply, {"max_sentences": 3}, tool_mode=True) == [
        "disse o rótulo interno 'registrar_meta'", "disse 'parcial' na aula", "placeholder na fala",
        "espanhol na aula de inglês: 'muy bien'", "4 frases (máximo 3)",
    ]


def test_outcome_words_count_only_in_the_lessons_and_echoing_the_learner_is_not_spanish():
    praise = Reply("That's correct! Nice job, Ana.")
    assert check_reply(praise, {}) == []
    assert check_reply(praise, {}, tool_mode=True) == ["disse 'Correct!' na aula"]
    echo = Reply("Você disse Hola, que é espanhol. Em inglês a gente diz Hi!")
    assert check_reply(echo, {}, learner="Hola, ¿cómo estás?") == []
    assert check_reply(echo, {}) == ["espanhol na aula de inglês: 'hola'"]


def test_reply_check_passes_a_clean_reply_and_reads_has_any_and_lacks():
    reply = Reply("Quase! Falta uma palavrinha antes do am. Tenta de novo?")
    assert check_reply(reply, {"max_sentences": 3, "lacks": ["I am Ana"]}) == []
    assert check_reply(reply, {"has_any": ["I am Ana", "I'm Ana"]}) == ["não disse nenhum de ['I am Ana', \"I'm Ana\"]"]


def test_reply_check_fails_an_empty_reply_and_a_tool_call_where_she_should_talk():
    assert check_reply(Reply(""), {}) == ["sem fala"]
    reply = Reply("Muito bem!", [ToolCall("c", "registrar_meta", "{}")])
    assert check_reply(reply, {}) == ["chamou ferramenta fora da avaliação: registrar_meta"]


def test_tool_check_reads_outcome_heard_and_correct_form():
    reply = Reply(calls=[ToolCall("c", "registrar_meta", json.dumps(
        {"resultado": "correto", "o_que_ouviu": "I am Ana", "forma_correta": ""},
    ))])
    assert check_tool(reply, {"name": "registrar_meta", "resultado": ["parcial", "incorreto"],
                              "heard_lacks": ["am"], "correct_has": ["I"]}) == [
        "resultado 'correto' (esperado parcial ou incorreto)",
        "o_que_ouviu com 'am': 'I am Ana'",
        "forma_correta sem 'I': ''",
    ]
    assert check_tool(Reply("Oi!"), {"name": "registrar_meta"}) == ["não chamou registrar_meta"]
    garbled = Reply(calls=[ToolCall("c", "registrar_meta", '{"resultado":')])
    assert check_tool(garbled, {"name": "registrar_meta"}) == ["argumentos ilegíveis: '{\"resultado\":'"]


# ── What the runner sends, and how it scores ─────────────────────────────────

def test_an_evaluation_is_a_system_message_and_a_forced_text_only_tool_call():
    connect, fakes = fake_connect([calls("registrar_meta", meta="1", resultado="fora_do_roteiro", o_que_ouviu="Sim")])
    result = asyncio.run(run_case(CASE["aula-sim"], runs=1, connect=connect, judge=None))

    assert (result.passes, result.failures) == (1, [])
    sent = fakes[0].sent
    system = [e["item"] for e in sent if e["type"] == "conversation.item.create" and e["item"].get("role") == "system"]
    assert system[0]["content"][0]["text"] == C.goal_context(1)
    assert sent[-1] == {"type": "response.create", "response": {
        "tool_choice": {"type": "function", "name": "registrar_meta"}, "output_modalities": ["text"],
    }}


def test_a_wrong_outcome_fails_every_run_and_keeps_the_transcript():
    connect, _ = fake_connect([calls("registrar_meta", meta="1", resultado="correto", o_que_ouviu="Sim")] * 2)
    result = asyncio.run(run_case(CASE["aula-sim"], runs=2, connect=connect, judge=None))

    assert result.passes == 0
    assert result.failures == [["resultado 'correto' (esperado fora_do_roteiro)"]] * 2
    assert result.transcript[-2:] == ["Aluno: Sim.", '[registrar_meta {"meta": "1", "resultado": "correto", "o_que_ouviu": "Sim"}]']


def test_earlier_calls_are_answered_in_the_history_and_the_last_one_by_the_case(mock_transport):
    seen: list = []
    all_passed_judge(mock_transport, seen)
    reply = "Quase! Falta uma palavrinha antes do am. Tenta de novo?"
    connect, fakes = fake_connect([say(reply)])
    result = asyncio.run(run_case(CASE["aula-primeiro-erro-pista"], runs=1, connect=connect, judge=judge))

    assert (result.passes, result.failures) == (1, [])
    # The judge reads the reply against the app's instruction she was following.
    context = seen[0]["input"][1]["content"].split("Fala da Flua:")[0]
    assert '[app para a Flua: parcial (tentativa 1 de 2). NÃO diga a resposta' in context
    items = [e["item"] for e in fakes[0].sent if e["type"] == "conversation.item.create"]
    call = next(item for item in items if item["type"] == "function_call")
    output = next(item for item in items if item["type"] == "function_call_output")
    assert output["call_id"] == call["call_id"]
    assert output["output"].startswith("parcial (tentativa 1 de 2).")
    # Any reply that is not an evaluation goes out with tool_choice none, as the clients do.
    assert fakes[0].sent[-1] == {"type": "response.create", "response": {"tool_choice": "none"}}


def test_a_past_call_followed_by_more_class_gets_its_output_before_the_class_goes_on():
    connect, fakes = fake_connect([calls("registrar_meta", meta="2", resultado="parcial", o_que_ouviu="She is teacher",
                                         forma_correta="She is a teacher.")])
    result = asyncio.run(run_case(CASE["aula-sem-artigo"], runs=1, connect=connect, judge=None))

    assert (result.passes, result.failures) == (1, [])
    kinds = [e["item"]["type"] if e["type"] == "conversation.item.create" else e["type"] for e in fakes[0].sent]
    first_call = kinds.index("function_call")
    assert kinds[first_call + 1] == "function_call_output"


def test_a_reply_that_gives_the_answer_away_fails_even_when_the_judge_passes_it(mock_transport):
    all_passed_judge(mock_transport)
    connect, _ = fake_connect([say("Quase! O certo é I am Ana. Tenta de novo?")])
    result = asyncio.run(run_case(CASE["aula-primeiro-erro-pista"], runs=1, connect=connect, judge=judge))
    assert result.failures == [["disse 'I am Ana'"]]


# Spec change (review of #10): an API error is a lost run, not a failure of the prompt.
def test_an_api_error_is_a_lost_run_not_a_failure_of_the_prompt():
    connect, _ = fake_connect(["error"])
    result = asyncio.run(run_case(CASE["aula-sim"], runs=1, connect=connect, judge=None))
    assert (result.passes, result.failures) == (0, [])
    assert result.errors == ['SessionError: {"message": "boom"}']


def test_a_dropped_websocket_is_a_lost_run_not_a_crash():
    connect, _ = fake_connect([], drop_at_response=True)
    result = asyncio.run(run_case(CASE["aula-sim"], runs=2, connect=connect, judge=None))
    assert (result.passes, result.failures) == (0, [])
    assert [error.split(":")[0] for error in result.errors] == ["ConnectionClosedError"] * 2


def test_free_practice_fails_when_every_reply_ends_in_a_question():
    connect, _ = fake_connect([say("Nice! What do you cook?"), say("Yum! Who cooks with you?"), say("Cool! Do you like it?")])
    result = asyncio.run(run_case(CASE["livre-nem-tudo-e-pergunta"], runs=1, connect=connect, judge=None))
    assert result.failures == [["todas as falas terminaram em pergunta"]]


# ── Judge ────────────────────────────────────────────────────────────────────

def test_judge_failures_quote_the_reply_and_count_a_criterion_it_skipped():
    verdict = {"criterios": [{"n": 1, "passou": False, "trecho": "não pediu nada"}]}
    assert failures_from_verdict(verdict, ["Pede para tentar de novo.", "Não diz a resposta."]) == [
        "Pede para tentar de novo. — não pediu nada", "juiz não avaliou: Não diz a resposta.",
    ]


def test_the_judge_asks_for_a_schema_bound_verdict_with_the_rubric(mock_transport, monkeypatch):
    monkeypatch.setenv("FLUA_EVAL_JUDGE_MODEL", "gpt-judge-test")
    seen: list = []
    all_passed_judge(mock_transport, seen)
    assert asyncio.run(judge("Oi, Ana!", ["Cumprimenta a Ana.", "Pergunta algo."], "(início da aula)")) == []
    body = seen[0]
    assert body["model"] == "gpt-judge-test"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["input"][1]["content"].endswith("Critérios:\n1. Cumprimenta a Ana.\n2. Pergunta algo.")


def test_the_judge_model_comes_from_the_environment_or_the_backend_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("FLUA_EVAL_JUDGE_MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    assert judge_model() == DEFAULT_JUDGE_MODEL
    (tmp_path / ".env").write_text("FLUA_EVAL_JUDGE_MODEL=claude-opus-5-5\n")
    assert judge_model() == "claude-opus-5-5"
    monkeypatch.setenv("FLUA_EVAL_JUDGE_MODEL", "gpt-5.5-mini")
    assert judge_model() == "gpt-5.5-mini"


# Spec change (review of #10): a failing judge loses the run (it no longer aborts the whole eval).
@pytest.mark.parametrize("answer", [
    judge_answers("insufficient_quota", status=429),
    judge_answers('{"criterios": [{"n": 1, "pass', state="incomplete"),
], ids=["no-credit", "cut-short"])
def test_a_failing_or_cut_short_judge_loses_the_run_instead_of_failing_the_case(mock_transport, answer):
    mock_transport(lambda request: answer)
    connect, _ = fake_connect([say("Quase! Falta uma palavrinha antes do am. Tenta de novo?")])
    result = asyncio.run(run_case(CASE["aula-primeiro-erro-pista"], runs=1, connect=connect, judge=judge))
    assert (result.passes, result.failures) == (0, [])
    assert result.errors[0].startswith("JudgeError: ")


def test_judge_without_json_is_a_failure(mock_transport):
    mock_transport(lambda request: judge_answers("Tudo certo."))
    assert asyncio.run(judge("Oi!", ["Cumprimenta."], "")) == ['juiz respondeu sem JSON: "Tudo certo."']


# ── Baseline comparison (the 2c acceptance rule) ─────────────────────────────

def _report(*cases, runs=3, errors=()):
    return {"runs": runs, "cases": [
        {"id": i, "category": cat, "passes": p, "runs": runs, "errors": list(errors) if i == "a" else []}
        for i, cat, p in cases
    ]}


def test_regressions_flag_a_category_drop_and_a_case_that_stopped_passing():
    baseline = _report(("a", "julgamento", 3), ("b", "julgamento", 1), ("c", "abertura", 0))
    current = _report(("a", "julgamento", 1), ("b", "julgamento", 2), ("c", "abertura", 3))
    assert regressions(current, baseline) == [
        "categoria julgamento: 3 contra 4 no baseline", "caso a: 1/3 (passava 3/3)",
    ]


def test_regressions_accept_two_of_three_and_compare_a_partial_run_on_what_it_ran():
    baseline = _report(("a", "julgamento", 3), ("b", "julgamento", 0), ("c", "abertura", 3))
    assert regressions(_report(("a", "julgamento", 2), ("b", "julgamento", 1)), baseline) == []
    assert regressions(_report(("a", "julgamento", 3), runs=1), baseline) == [
        "rodadas diferentes: 1 contra 3 no baseline",
    ]


def test_a_case_added_after_the_baseline_does_not_hide_an_old_one_getting_worse():
    baseline = _report(("a", "julgamento", 3), ("b", "julgamento", 3))
    current = _report(("a", "julgamento", 2), ("b", "julgamento", 2), ("new", "julgamento", 3))
    assert regressions(current, baseline) == ["categoria julgamento: 4 contra 6 no baseline"]


def test_runs_lost_to_the_api_block_the_comparison():
    baseline = _report(("a", "julgamento", 3))
    current = _report(("a", "julgamento", 2), errors=["SessionError: insufficient_quota"])
    assert regressions(current, baseline) == [
        "1 rodadas perdidas por erro da API ou do juiz: rode de novo antes de comparar",
    ]


def test_a_filtered_run_cannot_overwrite_the_baseline(monkeypatch):
    monkeypatch.setattr("sys.argv", ["evals.flua", "run", "--case", "aula-sim", "--save-baseline"])
    with pytest.raises(SystemExit, match="só com todos os casos"):
        cli.main()


def test_usage_sums_realtime_and_responses_token_counts_per_model():
    usage = Usage()
    usage.add("gpt-realtime-2.1-mini", {"input_tokens": 10, "input_token_details": {"cached_tokens": 4}, "output_tokens": 2})
    usage.add("gpt-realtime-2.1-mini", {"input_tokens": 5, "input_tokens_details": {"cached_tokens": 1}, "output_tokens": 3})
    usage.add("gpt-realtime-2.1-mini", None)
    assert usage.by_model["gpt-realtime-2.1-mini"] == Tokens(input=15, cached=5, output=5)
