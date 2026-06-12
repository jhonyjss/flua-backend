import httpx

from app.schemas.realtime import RealtimeSessionRequest
from app.services.realtime import build_tutor_instructions, cap_lesson_context


def test_cap_lesson_context():
    assert cap_lesson_context("x" * 5000) == "x" * 4000
    assert cap_lesson_context("short") == "short"


def test_instructions_include_name_level_and_context():
    req = RealtimeSessionRequest(
        level="beginner", studentName="Jhony", lessonContext="Lesson: verb to be", language="en",
    )
    text = build_tutor_instructions(req)
    assert "Jhony" in text
    assert "Portuguese" in text  # beginner style
    assert "verb to be" in text


def test_spanish_language_changes_target():
    req = RealtimeSessionRequest(language="es", level="advanced")
    assert "Spanish" in build_tutor_instructions(req)


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
