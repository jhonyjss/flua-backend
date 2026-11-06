import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.schemas.learning_intel import LearningProfile
from app.services.ai import tutor_respond


@pytest.mark.parametrize("has_answer", [True, False])
def test_tutor_sends_compatible_haiku_55_request(
    client, auth_headers, mock_transport, monkeypatch, has_answer
):
    monkeypatch.setenv("ANTHROPIC_MODEL_TEXT_TUTOR", "claude-haiku-5-5")
    monkeypatch.setattr(
        tutor_respond.learning_intel,
        "get_profile",
        AsyncMock(return_value=LearningProfile(level="A1")),
    )
    monkeypatch.setattr(tutor_respond.rag, "search", AsyncMock(return_value=[]))
    message = "Why do I say I am?"
    reply = "Com I, use am. Por exemplo, I am Ana."
    requests = []

    def provider(request):
        assert request.url.host == "api.anthropic.com"
        requests.append(json.loads(request.content))
        content = [{"type": "thinking", "thinking": ""}]
        if has_answer:
            content.append({"type": "text", "text": reply})
        return httpx.Response(
            200,
            json={
                "content": content,
                "stop_reason": "end_turn" if has_answer else "max_tokens",
            },
        )

    mock_transport(provider)
    response = client.post(
        "/api/ai/tutor/respond", headers=auth_headers, json={"message": message}
    )

    assert response.status_code == 200
    (payload,) = requests
    assert payload["model"] == "claude-haiku-5-5"
    assert payload["output_config"] == {"effort": "low"}
    assert {"temperature", "top_p", "top_k"}.isdisjoint(payload)
    assert payload["messages"] == [{"role": "user", "content": message}]
    assert "em português do Brasil" in payload["system"]
    assert response.json()["reply"] == (
        reply
        if has_answer
        else "Desculpa, tive um problema agora. Pode tentar de novo?"
    )
