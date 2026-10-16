import json
import time

import httpx
import jwt

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
    assert "hoje vão praticar Primeiros contatos" in opening


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


def test_retries_then_fails_on_5xx(client, auth_headers, mock_transport):
    calls = {"n": 0}

    def handler(request):
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


def test_free_practice_refused_when_period_minutes_are_spent(client, auth_headers, mock_transport):
    calls = []
    mock_transport(_plan_and_openai(plan_level="starter_monthly", consumed=10 * 60, calls=calls))
    res = client.post("/api/realtime/session", json={"mode": "free_practice"}, headers=auth_headers)
    assert res.status_code == 403
    assert res.json()["detail"]["expired"] is True
    assert calls == []


def test_free_practice_allowed_with_minutes_left(client, auth_headers, mock_transport):
    mock_transport(_plan_and_openai(plan_level="starter_monthly", consumed=120))
    res = client.post("/api/realtime/session", json={"mode": "free_practice"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["clientSecret"] == "ek_live_abc"


def test_free_practice_allowed_on_unlimited_plan(client, auth_headers, mock_transport):
    mock_transport(_plan_and_openai(plan_level="pro_yearly"))
    res = client.post("/api/realtime/session", json={"mode": "free_practice"}, headers=auth_headers)
    assert res.status_code == 200


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


def test_guided_lesson_stays_client_driven_even_if_asked_for_conversational():
    guided = RealtimeSessionRequest(
        mode="guided_lesson", lessonId="fund-u1-l1", plan=GUIDED_PLAN, turnMode="conversational"
    )
    free = RealtimeSessionRequest(mode="free_practice", turnMode="conversational")
    assert turn_mode_for(guided) == "educational"
    assert turn_mode_for(free) == "conversational"


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
