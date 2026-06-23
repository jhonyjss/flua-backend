import time

import httpx
import jwt

from app.core.auth import AuthUser
from app.schemas.realtime import RealtimeSessionRequest
from app.services.realtime import _turn_detection, build_tutor_instructions_from_request
from app.services.tutor_instructions import build_tutor_instructions, cap_lesson_context

from tests.conftest import JWT_SECRET


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
    assert data["model"] == "gpt-realtime"
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
