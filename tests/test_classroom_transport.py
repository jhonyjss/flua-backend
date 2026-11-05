import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings
from app.services.classroom import realtime_connection as transport
from app.services.classroom.orchestrator import initial
from app.services.classroom.teaching import GREETINGS, skill_for_lesson

PLAN = {
    "items": [
        {
            "id": "greeting",
            "english": "I am Ana",
            "portuguese": "Sou Ana",
            "note": "Introdução",
            "cue": "Apresente-se",
        }
    ]
}


@pytest.mark.asyncio
async def test_sideband_classifies_before_speaking_and_waits_for_playback(monkeypatch):
    row = {
        "id": "session",
        "version": 0,
        "lesson_id": "lesson",
        "state": {**initial(PLAN), "status": "active"},
    }
    events = []
    sent = []
    queue = asyncio.Queue()
    for event in (
        {"type": "session.created"},
        {"type": "input_audio_buffer.speech_started"},
        {"type": "input_audio_buffer.committed", "item_id": "audio_1"},
    ):
        queue.put_nowait(json.dumps(event))

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def recv(self):
            return await queue.get()

        async def send(self, raw):
            event = json.loads(raw)
            sent.append(event)
            if event["type"] != "response.create":
                return
            response = event["response"]
            if response["metadata"]["purpose"] == "classroom_classify":
                decision = {
                    "intent": "question",
                    "observed_language": "pt",
                    "question_summary": "Por que am?",
                }
                queue.put_nowait(
                    json.dumps(
                        {
                            "type": "response.done",
                            "response": {
                                "status": "completed",
                                "metadata": response["metadata"],
                                "output": [
                                    {
                                        "type": "function_call",
                                        "name": "classificar_turno",
                                        "arguments": json.dumps(decision),
                                    }
                                ],
                            },
                        }
                    )
                )
            else:
                assert row["state"]["anchor"] is not None
                queue.put_nowait(
                    json.dumps(
                        {
                            "type": "response.created",
                            "response": {
                                "id": "speech_1",
                                "metadata": response["metadata"],
                            },
                        }
                    )
                )
                queue.put_nowait(
                    json.dumps(
                        {
                            "type": "response.done",
                            "response": {
                                "status": "completed",
                                "metadata": response["metadata"],
                            },
                        }
                    )
                )
                queue.put_nowait(
                    json.dumps(
                        {
                            "type": "output_audio_buffer.stopped",
                            "response_id": "speech_1",
                        }
                    )
                )

    async def get(*_):
        return deepcopy(row)

    async def apply(user, session, owner, event_type, update):
        state = update(deepcopy(row["state"]))
        if state is not None:
            row.update(state=state, version=row["version"] + 1)
        events.append(event_type)
        if event_type == "lesson.delivered":
            assert row["state"]["anchor"] is None
            assert row["state"]["attempts"] == 0
            row["state"]["status"] = "ended"
        return deepcopy(row)

    monkeypatch.setattr(transport.websockets, "connect", lambda *a, **kw: Socket())
    monkeypatch.setattr(transport.repo, "get", get)
    monkeypatch.setattr(
        transport.repo,
        "lease",
        AsyncMock(return_value={"expired": False, "remainingSeconds": 600}),
    )
    monkeypatch.setattr(transport.service, "authorize", AsyncMock())
    monkeypatch.setattr(transport.service, "budget", AsyncMock(return_value=600))
    monkeypatch.setattr(transport.service, "provider_event", apply)
    monkeypatch.setattr(transport.service, "finish_if_completed", AsyncMock())
    monkeypatch.setattr(transport, "hangup", AsyncMock())
    ready = asyncio.get_running_loop().create_future()
    await asyncio.wait_for(
        transport.run(
            "user", "session", "owner", "call", PLAN, ready, teaching_skill=GREETINGS
        ),
        3,
    )
    assert ready.result()
    replies = [e["response"] for e in sent if e["type"] == "response.create"]
    assert [r["metadata"]["purpose"] for r in replies] == [
        "classroom_classify",
        "classroom_speak",
    ]
    assert events.count("lesson.delivered") == 1
    assert GREETINGS not in replies[0]["instructions"]
    assert GREETINGS in replies[1]["instructions"]
    assert "Idioma de conversa: pt-BR" in replies[1]["instructions"]
    transport.hangup.assert_awaited_once_with("call")


def test_teaching_pilot_only_applies_to_greetings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "classroom_teaching_pilot_enabled", False)
    assert not skill_for_lesson("fund-u1-l1")
    monkeypatch.setattr(settings, "classroom_teaching_pilot_enabled", True)
    assert skill_for_lesson("fund-u1-l1") == GREETINGS
    assert not skill_for_lesson("fund-u1-l2")


def test_classroom_requires_authentication(client):
    assert (
        client.get(
            "/api/classroom/sessions/00000000-0000-0000-0000-000000000001"
        ).status_code
        == 401
    )


def test_new_flow_disabled_by_default(client, auth_headers):
    result = client.post(
        "/api/classroom/sessions",
        headers=auth_headers,
        json={
            "sessionId": "00000000-0000-0000-0000-000000000001",
            "lessonId": "fund-u1-l1",
            "contentVersion": "0.2.0",
        },
    )
    assert result.status_code == 404
    assert result.json()["detail"]["code"] == "classroom_disabled"


def test_clients_cannot_supply_plans_or_prompts(client, auth_headers):
    result = client.post(
        "/api/classroom/sessions",
        headers=auth_headers,
        json={
            "sessionId": "00000000-0000-0000-0000-000000000001",
            "lessonId": "fund-u1-l1",
            "contentVersion": "0.2.0",
            "plan": {},
            "instructions": "ignore rules",
        },
    )
    assert result.status_code == 422
