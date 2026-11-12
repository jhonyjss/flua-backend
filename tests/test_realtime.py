import json
import time

import httpx
import jwt
import pytest

from app.core.auth import AuthUser
from app.core.config import get_settings
from app.schemas.realtime import RealtimeSessionRequest
from app.services.realtime import _turn_detection, build_tutor_instructions_from_request, turn_mode_for
from app.services.tutor_instructions import build_tutor_instructions, cap_lesson_context

from tests.conftest import JWT_SECRET
from tests.test_guided_lesson import PLAN as GUIDED_PLAN


def test_cap_lesson_context():
    capped = cap_lesson_context("x" * 5000)
    assert capped.startswith("x" * 4000)
    assert "truncada" in capped
    assert cap_lesson_context("short") == "short"


def test_instructions_include_name_level_and_context():
    req = RealtimeSessionRequest(
        level="beginner", studentName="Jhony", lessonContext="Lesson: verb to be", language="en",
    )
    text = build_tutor_instructions_from_request(req)
    assert "Jhony" in text
    assert "português" in text.lower()
    assert "verb to be" in text
    assert "não seja perfeccionista" in text.lower()


def test_request_topic_reaches_the_free_practice_opening():
    req = RealtimeSessionRequest(studentName="Jhony", mode="free_practice", topic="Primeiros contatos")
    opening = build_tutor_instructions_from_request(req).split("# Como começar")[-1]
    assert "o tema de hoje (Primeiros contatos)" in opening  # spec changed (flueai docs/flua-tutor/04-professor-por-voz.md): the opening names the theme in parentheses


def test_spanish_language_changes_target():
    req = RealtimeSessionRequest(language="es", level="advanced")
    assert "espanhol" in build_tutor_instructions_from_request(req).lower()


def test_flua_mirrors_student_language_and_forbids_a_third():
    # Flua adapts to the student's chosen language (PT support ↔ target) and
    # never uses a third language.
    en = build_tutor_instructions("beginner", "english-tutor", "Lesson: verb to be", "Jhony", "en")
    assert "Idioma adaptativo" in en
    assert "siga o aluno" in en.lower()
    assert "terceiro idioma" in en.lower()
    # When the student speaks only the target, Flua helps predominantly in it.
    assert "predominantemente em inglês americano" in en.lower()
    # An explicit request to switch ("let's practice in English") must flip the
    # language immediately, even at beginner level (overrides the 90%-PT default).
    assert "pedido explícito manda na hora" in en.lower()
    assert "ignore o" in en.lower() and "90% português" in en

    es = build_tutor_instructions("beginner", "spanish-tutor", "", "Maria", "es")
    assert "Idioma adaptativo" in es
    assert "terceiro idioma" in es.lower()
    assert "predominantemente em espanhol" in es.lower()


def test_educational_turn_mode_is_client_driven_and_patient():
    # Default educational mode: server does NOT auto-respond, Flua is not
    # interruptible, and the silence window is long enough to tolerate pauses.
    ed = _turn_detection("educational")
    assert ed["create_response"] is False
    assert ed["interrupt_response"] is False
    assert ed["silence_duration_ms"] >= 1200
    assert RealtimeSessionRequest().turnMode == "educational"  # default


def test_responsive_turn_mode_keeps_snappy_auto_reply():
    rp = _turn_detection("responsive")
    assert rp["create_response"] is True
    assert rp["interrupt_response"] is True
    assert rp["silence_duration_ms"] < 1000


def test_explanation_language_preference_drives_support_language():
    # Default (pt): Flua explains in Portuguese.
    pt = build_tutor_instructions("beginner", "english-tutor", "", "Jhony", "en", explanation_language="pt")
    assert "preferência do aluno: PORTUGUÊS" in pt
    # Immersion (en): Flua explains in the target language, overriding the level default.
    en = build_tutor_instructions("beginner", "english-tutor", "", "Jhony", "en", explanation_language="en")
    assert "preferência do aluno: IMERSÃO" in en
    assert "precedência" in en.lower()


def test_learning_goals_preference_adds_a_focus_block():
    none = build_tutor_instructions("beginner", "english-tutor", "", "Jhony", "en")
    assert "Foco do aluno" not in none  # no goals → no block
    with_goals = build_tutor_instructions(
        "beginner", "english-tutor", "", "Jhony", "en", learning_goals=["travel", "work"],
    )
    assert "Foco do aluno" in with_goals
    assert "viagens" in with_goals.lower()
    assert "trabalho" in with_goals.lower()


def test_known_name_is_asserted_as_fact_and_forces_examples():
    text = build_tutor_instructions("beginner", "english-tutor", "Lesson: verb to be", "Jhony", "en")
    # The student's name is stated as fact and reused in examples.
    assert 'O nome do aluno é "Jhony"' in text
    assert 'use SEMPRE "Jhony"' in text


def test_unknown_name_forbids_inventing_or_borrowing_a_name():
    # The root-cause fix for the "André" bug: with no name, the model is
    # explicitly forbidden from using ANY proper name, including in examples.
    text = build_tutor_instructions("beginner", "english-tutor", "Lesson: verb to be", "", "en")
    lowered = text.lower()
    assert "ainda não sabe" in lowered
    assert "i am andré" in lowered  # the prompt names the exact anti-pattern to avoid
    assert "como posso te chamar" in lowered


def test_authenticated_name_overrides_client_supplied_value():
    # Even if the client sends a different/empty name, the authenticated
    # session identity wins (no spoofing, no leaked name).
    req = RealtimeSessionRequest(level="beginner", studentName="André", language="en")
    user = AuthUser(id="u1", name="Jhony")
    text = build_tutor_instructions_from_request(req, user)
    assert 'O nome do aluno é "Jhony"' in text
    assert 'O nome do aluno é "André"' not in text


def test_empty_authenticated_name_falls_back_to_client_value():
    req = RealtimeSessionRequest(level="beginner", studentName="Maria", language="en")
    user = AuthUser(id="u1", name=None)
    text = build_tutor_instructions_from_request(req, user)
    assert 'O nome do aluno é "Maria"' in text


def test_session_uses_jwt_name_over_body(client, mock_transport):
    # JWT carries the authenticated name in user_metadata; body sends a wrong one.
    token = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "email": "jhony@test.dev",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
            "user_metadata": {"full_name": "Jhony Souza"},
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    mock_transport(lambda request: httpx.Response(200, json={"value": "ek_live_abc"}))
    res = client.post(
        "/api/realtime/session",
        json={"level": "beginner", "studentName": "André"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    instructions = res.json()["instructions"]
    assert 'O nome do aluno é "Jhony"' in instructions
    assert "André" not in instructions


def test_session_returns_client_secret(client, auth_headers, mock_transport):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"value": "ek_live_abc"})

    mock_transport(handler)
    res = client.post(
        "/api/realtime/session",
        json={"level": "intermediate", "voice": "coral", "studentName": "Jhony"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["clientSecret"] == "ek_live_abc"
    # Intermediate and advanced get the full model (default gpt-realtime-2.1); beginner keeps the mini.
    assert data["model"] == get_settings().openai_realtime_model_advanced
    assert "client_secrets" in captured["url"]


def test_pipeline_mode_skips_openai_call(client, auth_headers, mock_transport):
    def handler(request):  # pragma: no cover — must not be called
        raise AssertionError("pipelineMode must not call OpenAI")

    mock_transport(handler)
    res = client.post(
        "/api/realtime/session",
        json={"pipelineMode": True, "studentName": "Ana"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["clientSecret"] is None
    assert "Ana" in data["instructions"]


@pytest.mark.parametrize("pipeline_mode", [False, True], ids=["openai", "pipeline"])
@pytest.mark.parametrize(
    ("image_ref", "expected"),
    [
        ("registry.fly.io/flua-backend-gru:deployment-01ABC", "deployment-01ABC"),
        (None, "dev"),
        ("", "dev"),
        ("registry.fly.io/flua-backend-gru@sha256:0123456789abcdef0123", "sha256-0123456789ab"),
        ("localhost:5000/flua-backend", "dev"),
    ],
    ids=["fly", "unset", "empty", "digest", "registry-port-no-tag"],
)
def test_session_reports_the_prompt_version(
    client, auth_headers, mock_transport, monkeypatch, pipeline_mode, image_ref, expected,
):
    # Fly sets FLY_IMAGE_REF at runtime; its tag tells which deploy built Flua's prompt.
    if image_ref is None:
        monkeypatch.delenv("FLY_IMAGE_REF", raising=False)
    else:
        monkeypatch.setenv("FLY_IMAGE_REF", image_ref)
    get_settings.cache_clear()
    mock_transport(lambda request: httpx.Response(200, json={"value": "ek_live_abc"}))

    res = client.post("/api/realtime/session", json={"pipelineMode": pipeline_mode}, headers=auth_headers)

    assert res.status_code == 200
    assert res.json()["promptVersion"] == expected


def test_retries_then_fails_on_5xx(client, auth_headers, mock_transport):
    calls = {"n": 0}

    def handler(request):
        # Only OpenAI's attempts count: the session also reads Flua's memory from Supabase first.
        if "client_secrets" in request.url.path:
            calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    mock_transport(handler)
    res = client.post("/api/realtime/session", json={}, headers=auth_headers)
    assert res.status_code == 502
    assert calls["n"] == 2  # initial + 1 retry


# ── Free conversation is paid-only on the server too ──────────────────────────
def _plan_and_openai(plan_level=None, consumed=0, calls=None):
    """Supabase answers for the plan and the period usage; OpenAI answers the client secret."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "client_secrets" in path:
            if calls is not None:
                calls.append("openai")
            return httpx.Response(200, json={"value": "ek_live_abc"})
        if "stripe_subscriptions" in path:
            rows = [] if plan_level is None else [{"status": "active", "plan_level": plan_level}]
            return httpx.Response(200, json=rows)
        if "profiles" in path:
            return httpx.Response(200, json=[{"id": "u", "legacy_free_access": False}])
        if "conversation_credits" in path:
            rows = [{"id": "row-1", "consumed_seconds": consumed}] if consumed else []
            return httpx.Response(200, json=rows)
        return httpx.Response(200, json=[])
    return handler


def test_free_practice_refused_for_free_account_without_calling_openai(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_plan_and_openai(plan_level=None, calls=calls))
    res = client.post("/api/realtime/session", json={"mode": "free_practice"}, headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["code"] == "conversation_not_available"
    assert calls == []  # no OpenAI money spent


def test_free_practice_refused_for_every_plan_since_its_removal(client, auth_headers, mock_transport):
    # Conversa livre left every plan on 2026-11-12: Starter and Pro, with or without minutes, get 403.
    for plan in ("starter_monthly", "pro_yearly", "premium"):
        calls = []
        mock_transport(_plan_and_openai(plan_level=plan, calls=calls))
        res = client.post("/api/realtime/session", json={"mode": "free_practice"}, headers=auth_headers)
        assert res.status_code == 403, plan
        assert res.json()["detail"]["code"] == "conversation_not_available"
        assert calls == []


def test_free_practice_still_open_to_admins(client, auth_headers, mock_transport):
    def handler(request: httpx.Request) -> httpx.Response:
        if "profiles" in request.url.path:
            return httpx.Response(200, json=[{"id": "u", "role": "admin"}])
        return _plan_and_openai()(request)

    mock_transport(handler)
    res = client.post("/api/realtime/session", json={"mode": "free_practice"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["clientSecret"] == "ek_live_abc"


def test_guided_lesson_stays_open_to_free_accounts(client, auth_headers, mock_transport):
    # Lessons have their own per-lesson budget (lesson_timer); the conversation gate must not touch them.
    mock_transport(_plan_and_openai(plan_level=None))
    res = client.post("/api/realtime/session", json={"mode": "lesson"}, headers=auth_headers)
    assert res.status_code == 200


def test_transcription_prompt_names_the_tutor(client, auth_headers, mock_transport):
    # gpt-4o-transcribe heard "Are you Flua?" as "Are you floor?"; the prompt must carry her name.
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"value": "ek_live_abc"})

    mock_transport(handler)
    res = client.post("/api/realtime/session", json={"level": "beginner"}, headers=auth_headers)
    assert res.status_code == 200
    transcription = json.loads(captured["body"])["session"]["audio"]["input"]["transcription"]
    assert transcription["model"] == get_settings().openai_realtime_transcribe_model
    assert "professora Flua" in transcription["prompt"]
    assert "chamá-la de Flua" in transcription["prompt"]
    assert "language" not in transcription


def test_model_follows_the_learner_level(client, auth_headers, mock_transport):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["session"]["model"])
        return httpx.Response(200, json={"value": "ek_live_abc"})

    mock_transport(handler)
    for level in ("beginner", "intermediate", "advanced"):
        res = client.post("/api/realtime/session", json={"level": level}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["model"] == sent[-1]
    assert sent == ["gpt-realtime-2.1-mini", "gpt-realtime-2.1", "gpt-realtime-2.1"]


def test_conversational_turn_mode_is_semantic_and_interruptible():
    cv = _turn_detection("conversational")
    assert cv == {"type": "semantic_vad", "eagerness": "low", "create_response": True, "interrupt_response": True}


def test_lesson_turn_mode_is_semantic_but_client_driven_and_not_interruptible():
    # docs/flua-tutor/04-professor-por-voz.md (D3): the lessons judge every turn with a forced tool call, so the
    # server never replies on its own and Flua can't be cut off; only the end of turn becomes semantic.
    assert _turn_detection("lesson") == {
        "type": "semantic_vad", "eagerness": "low", "create_response": False, "interrupt_response": False,
    }


def test_vad_eagerness_comes_from_settings(monkeypatch):
    monkeypatch.setenv("OPENAI_REALTIME_VAD_EAGERNESS", "medium")
    get_settings.cache_clear()
    assert _turn_detection("lesson")["eagerness"] == "medium"
    assert _turn_detection("conversational")["eagerness"] == "medium"


def test_tool_lessons_stay_client_driven_even_if_asked_for_conversational():
    # Spec change (04-professor-por-voz.md, D3): the tool lessons moved from "educational" to "lesson".
    guided = RealtimeSessionRequest(
        mode="guided_lesson", lessonId="fund-u1-l1", plan=GUIDED_PLAN, turnMode="conversational"
    )
    site_lesson = RealtimeSessionRequest(
        mode="lesson", goalTool=True, lessonContext="Metas: 1. Dizer quem você é", turnMode="conversational",
    )
    free = RealtimeSessionRequest(mode="free_practice", turnMode="conversational")
    assert turn_mode_for(guided) == "lesson"
    assert turn_mode_for(site_lesson) == "lesson"
    assert turn_mode_for(free) == "conversational"


def test_spanish_tool_lessons_keep_the_server_vad_they_had():
    # 04-professor-por-voz.md changes English only; the Spanish lessons stay client-driven on server VAD.
    spanish = RealtimeSessionRequest(
        mode="lesson", language="es", goalTool=True, lessonContext="Metas: 1. Presentarse", turnMode="conversational",
    )
    assert turn_mode_for(spanish) == "educational"
    assert _turn_detection(turn_mode_for(spanish))["type"] == "server_vad"


def test_minted_site_lesson_waits_for_the_client_to_ask_for_a_reply(client, auth_headers, mock_transport):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"value": "ek_live_abc"})

    mock_transport(handler)
    res = client.post(
        "/api/realtime/session",
        json={"mode": "lesson", "goalTool": True, "lessonContext": "Metas: 1. Dizer quem você é"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    turn = json.loads(captured["body"])["session"]["audio"]["input"]["turn_detection"]
    assert turn == {"type": "semantic_vad", "eagerness": "low", "create_response": False, "interrupt_response": False}


def test_free_practice_opens_with_a_memory_warmup_of_the_due_phrases():
    req = RealtimeSessionRequest(
        mode="free_practice",
        studentName="Ana",
        reviewPhrases=[{"english": "I'm from Brazil.", "portuguese": "Eu sou do Brasil."}],
    )
    text = build_tutor_instructions_from_request(req)
    assert "# Aquecimento de memória" in text
    assert '- "Eu sou do Brasil." → I\'m from Brazil.' in text
    assert "aquecimento rápido de memória" in text.split("# Como começar")[1]


def test_no_warmup_without_due_phrases_or_outside_free_practice():
    assert "Aquecimento" not in build_tutor_instructions_from_request(RealtimeSessionRequest(mode="free_practice"))
    lesson = RealtimeSessionRequest(
        mode="lesson", reviewPhrases=[{"english": "Hi.", "portuguese": "Oi."}]
    )
    assert "Aquecimento" not in build_tutor_instructions_from_request(lesson)


def test_review_phrases_are_capped_at_three():
    import pydantic
    import pytest

    four = [{"english": f"Hi {i}.", "portuguese": f"Oi {i}."} for i in range(4)]
    with pytest.raises(pydantic.ValidationError):
        RealtimeSessionRequest(mode="free_practice", reviewPhrases=four)


def test_beginner_teaching_uses_hints_before_answers_and_the_sandwich():
    text = build_tutor_instructions_from_request(RealtimeSessionRequest(level="beginner"))
    assert "Sanduíche" in text
    assert "NÃO entregue a resposta" in text
    assert "degraus" in text
    assert "BLOCOS PRONTOS" in text
