import json

import httpx

from app.schemas.realtime import RealtimeSessionRequest
from app.services.realtime import build_tutor_instructions_from_request

MISTAKE = {"said": "She have a dog.", "natural": "She has a dog.", "tip": "Com she, usamos has.", "source": "conversation"}


def test_records_a_correction_for_the_signed_in_account(client, auth_headers, mock_transport):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append((request.method, request.url.path, json.loads(request.content or b"null")))
        return httpx.Response(201, json=[{"id": 1}])

    mock_transport(handler)
    res = client.post("/api/users/me/mistakes", json=MISTAKE, headers=auth_headers)
    assert res.status_code == 204
    method, path, body = sent[0]
    assert (method, path) == ("POST", "/rest/v1/learner_mistakes")
    assert body["said"] == "She have a dog."
    assert body["source"] == "conversation"
    assert body["user_id"]


def test_a_failed_write_is_not_the_learners_problem(client, auth_headers, mock_transport):
    mock_transport(lambda request: httpx.Response(500, text="boom"))
    assert client.post("/api/users/me/mistakes", json=MISTAKE, headers=auth_headers).status_code == 204


def test_refuses_an_unknown_source_and_needs_an_account(client, auth_headers, mock_transport):
    mock_transport(lambda request: httpx.Response(201, json=[]))
    bad = {**MISTAKE, "source": "elsewhere"}
    assert client.post("/api/users/me/mistakes", json=bad, headers=auth_headers).status_code == 422
    assert client.post("/api/users/me/mistakes", json=MISTAKE).status_code in (401, 403)


def test_a_new_session_brings_back_the_newest_distinct_mistakes(client, auth_headers, mock_transport):
    rows = [
        {"said": "She have a dog.", "natural": "She has a dog.", "tip": "Com she, usamos has."},
        {"said": "He have a car.", "natural": "He has a car.", "tip": "com she, usamos HAS."},  # same tip
        {"said": "I am agree.", "natural": "I agree.", "tip": "Agree já é verbo."},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if "learner_mistakes" in request.url.path:
            return httpx.Response(200, json=rows)
        return httpx.Response(200, json={"value": "ek_live_abc"})

    mock_transport(handler)
    res = client.post("/api/realtime/session", json={"level": "beginner"}, headers=auth_headers)
    assert res.status_code == 200
    instructions = res.json()["instructions"]
    assert "# Memória do aluno" in instructions
    assert '- disse "She have a dog." → "She has a dog." (Com she, usamos has.)' in instructions
    assert "He have a car." not in instructions
    assert '- disse "I am agree." → "I agree." (Agree já é verbo.)' in instructions


def test_no_memory_block_when_reading_fails():
    req = RealtimeSessionRequest(level="beginner")
    assert "Memória do aluno" not in build_tutor_instructions_from_request(req, None, [])


def test_the_guided_lesson_does_not_read_the_memory(client, auth_headers, mock_transport):
    from tests.test_guided_lesson import PLAN

    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if "client_secrets" in request.url.path:
            return httpx.Response(200, json={"value": "ek_live_abc"})
        return httpx.Response(200, json=[])

    mock_transport(handler)
    client.post(
        "/api/realtime/session",
        json={"mode": "guided_lesson", "lessonId": "fund-u1-l1", "plan": PLAN},
        headers=auth_headers,
    )
    assert not any("learner_mistakes" in path for path in paths)
