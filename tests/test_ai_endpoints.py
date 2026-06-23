import json

import httpx

from app.services.anthropic_client import extract_json


def anthropic_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json={
        "content": [{"type": "text", "text": json.dumps(payload)}],
    })


GRAMMAR_PAYLOAD = {
    "hasErrors": True,
    "issues": [{
        "original": "I goed",
        "correction": "I went",
        "explanation": "Irregular past tense",
        "explanationPt": "Passado irregular",
        "category": "verb-tense",
        "severity": "important",
    }],
    "correctedMessage": "I went to school",
    "encouragement": "Nice try!",
    "encouragementPt": "Boa tentativa!",
    "phrasesUsed": ["I went"],
    "overallScore": 72,
}


def test_grammar_analysis_returns_parsed_result(client, auth_headers, mock_transport):
    mock_transport(lambda request: anthropic_response(GRAMMAR_PAYLOAD))
    res = client.post(
        "/api/ai/grammar-analysis",
        json={"userMessage": "I goed to school", "userLevel": "beginner"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["hasErrors"] is True
    assert data["issues"][0]["correction"] == "I went"
    assert data["overallScore"] == 72


def test_grammar_analysis_clamps_out_of_range_score(client, auth_headers, mock_transport):
    mock_transport(lambda request: anthropic_response({**GRAMMAR_PAYLOAD, "overallScore": 250}))
    res = client.post(
        "/api/ai/grammar-analysis",
        json={"userMessage": "hello"},
        headers=auth_headers,
    )
    assert res.json()["overallScore"] == 100


def test_grammar_analysis_handles_non_json_model_output(client, auth_headers, mock_transport):
    mock_transport(lambda request: httpx.Response(200, json={
        "content": [{"type": "text", "text": "sorry, I cannot do that"}],
    }))
    res = client.post("/api/ai/grammar-analysis", json={"userMessage": "hi"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["success"] is False


def test_grammar_analysis_requires_auth(client):
    res = client.post("/api/ai/grammar-analysis", json={"userMessage": "hi"})
    assert res.status_code == 401


def test_grammar_analysis_validates_body(client, auth_headers):
    res = client.post("/api/ai/grammar-analysis", json={"userMessage": ""}, headers=auth_headers)
    assert res.status_code == 422


def test_learning_recommendations(client, auth_headers, mock_transport):
    payload = {
        "focusAreas": [{"title": "Pronúncia", "description": "Pratique sons difíceis.", "severity": "high"}],
        "recommendedTopics": ["past simple"],
        "motivationPt": "Você está indo bem!",
    }
    mock_transport(lambda request: anthropic_response(payload))
    res = client.post(
        "/api/ai/learning-recommendations",
        json={"userLevel": "intermediate", "streakDays": 5, "totalLessonsCompleted": 10},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["focusAreas"][0]["severity"] == "high"


def test_conversation_response(client, auth_headers, mock_transport):
    mock_transport(lambda request: httpx.Response(200, json={
        "content": [{"type": "text", "text": "Great! Where do you want to travel?"}],
    }))
    res = client.post(
        "/api/ai/conversation-response",
        json={
            "userMessage": "I want to travel",
            "conversationHistory": [{"role": "user", "message": "I want to travel"}],
            "scenario": "english-tutor",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "travel" in data["response"]


def test_conversation_system_prompt_includes_lesson_context():
    from app.schemas.ai import ConversationResponseRequest, LessonContextBlock
    from app.services.ai.conversation import build_system_prompt

    req = ConversationResponseRequest(
        userMessage="Hello",
        teacherMode=True,
        lessonContext=LessonContextBlock(
            currentTopic="Greetings",
            keyPhrases=["How are you?", "Nice to meet you"],
        ),
    )
    prompt = build_system_prompt(req)
    assert "How are you?" in prompt
    assert "TEACHER MODE" in prompt or "teacher" in prompt.lower()


def test_anthropic_upstream_error_returns_failure(client, auth_headers, mock_transport):
    mock_transport(lambda request: httpx.Response(529, text="overloaded"))
    res = client.post(
        "/api/ai/conversation-response",
        json={"userMessage": "hi"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["success"] is False


def test_extract_json_handles_code_fences():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Here you go: {"a": {"b": 2}} hope it helps') == {"a": {"b": 2}}


def test_transcribe_json_endpoint(client, auth_headers, mock_transport):
    import base64

    deepgram = {
        "results": {"channels": [{"alternatives": [{"transcript": "hello world", "confidence": 0.98}]}]},
    }
    mock_transport(lambda request: httpx.Response(200, json=deepgram))
    res = client.post(
        "/api/ai/transcribe",
        json={"audio": base64.b64encode(b"\x00\x01" * 100).decode(), "sampleRate": 16000},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["transcript"] == "hello world"
    assert data["confidence"] == 0.98


def test_transcribe_multipart_endpoint(client, auth_headers, mock_transport):
    deepgram = {
        "results": {"channels": [{"alternatives": [{"transcript": "hello world", "confidence": 0.98}]}]},
    }
    mock_transport(lambda request: httpx.Response(200, json=deepgram))
    res = client.post(
        "/api/ai/transcribe",
        files={"audio": ("clip.webm", b"fake-bytes", "audio/webm")},
        data={"language": "en"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["transcript"] == "hello world"
    assert data["confidence"] == 0.98
