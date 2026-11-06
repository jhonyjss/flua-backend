from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.schemas.classroom import Command, Start, TurnDecision
from app.services.classroom import content, roleplay, service
from app.services.classroom import orchestrator as machine

PLAN = content.lesson(roleplay.LESSON_ID, "0.2.0")


@pytest.fixture
def session(monkeypatch):
    row = None

    async def authorize(*_, **__):
        pass

    async def select_one(table, _):
        return deepcopy(row) if table == "classroom_sessions" else None

    async def insert(_, fields):
        nonlocal row
        row = {**fields, "version": 0}
        return deepcopy(row)

    async def get(*_):
        return deepcopy(row)

    async def save(_user, _row, _event_id, _event_type, state, _payload):
        row.update(state=state, version=row["version"] + 1)
        return deepcopy(row)

    monkeypatch.setattr(service, "enabled", lambda _: None)
    monkeypatch.setattr(service, "authorize", authorize)
    monkeypatch.setattr(service.db, "select_one", select_one)
    monkeypatch.setattr(service.db, "insert", insert)
    monkeypatch.setattr(service.repo, "get", get)
    monkeypatch.setattr(service.repo, "save", save)

    async def open_session(*, pilot):
        monkeypatch.setattr(get_settings(), "classroom_roleplay_pilot_enabled", pilot)
        await service.start(
            "user",
            Start(
                sessionId=uuid4(), lessonId=roleplay.LESSON_ID, contentVersion="0.2.0"
            ),
        )
        return row

    return open_session


async def command(row, kind, **fields):
    return await service.command(
        "user",
        row["id"],
        Command(commandId=uuid4(), expectedVersion=row["version"], type=kind, **fields),
    )


@pytest.mark.asyncio
async def test_greetings_storyboard_requires_each_matching_panel_ack(session):
    row = await session(pilot=True)
    await command(row, "ready")
    assert roleplay.INTRO in row["state"]["pendingInstruction"]
    row["state"] = machine.delivered(row["state"], PLAN)

    for index, line in enumerate(
        [
            "Hello, Ana!",
            "Hello, Flua!",
            "I am Flua.",
            "My name is Ana.",
            "Goodbye, Ana!",
        ],
        1,
    ):
        expected = f"greeting-{index}"
        assert roleplay.panel(row["state"])["id"] == expected
        assert not row["state"]["pendingInstruction"]
        with pytest.raises(HTTPException) as stale:
            await command(row, "panel_ready", panelId="greeting-99")
        assert stale.value.status_code == 409
        await command(row, "panel_ready", panelId=expected)
        assert f'"{line}"' in row["state"]["pendingInstruction"]
        before = deepcopy(row)
        await command(row, "panel_ready", panelId=expected)
        assert row == before
        row["state"] = machine.delivered(row["state"], PLAN)

    assert "roleplay" not in row["state"]
    assert row["state"]["stage"] == "repetir"
    assert row["state"]["attempts"] == 0
    assert "Agora é sua vez" in row["state"]["pendingInstruction"]


@pytest.mark.asyncio
async def test_question_during_image_load_does_not_cancel_reply_or_grade(session):
    row = await session(pilot=True)
    await command(row, "ready")
    row["state"] = machine.delivered(row["state"], PLAN)
    row["state"] = machine.transition(
        PLAN,
        row["state"],
        TurnDecision(
            intent="question", observed_language="en", question_summary="Hello?"
        ),
    )
    before = deepcopy(row["state"])
    await command(row, "panel_ready", panelId="greeting-1")
    assert row["state"]["generation"] == before["generation"]
    assert row["state"]["pendingInstruction"] == before["pendingInstruction"]
    row["state"] = machine.delivered(row["state"], PLAN)
    assert row["state"]["roleplayPlayback"] == "greeting-1"
    assert row["state"]["attempts"] == 0
    assert row["state"]["language"] == "pt-BR"


@pytest.mark.asyncio
async def test_resume_does_not_repeat_completed_panel_and_waits_for_image(session):
    row = await session(pilot=True)
    await command(row, "ready")
    row["state"] = machine.delivered(row["state"], PLAN)
    await command(row, "panel_ready", panelId="greeting-1")
    row["state"] = machine.delivered(row["state"], PLAN)
    await command(row, "panel_ready", panelId="greeting-2")
    await command(row, "pause")
    roleplay.reset_connection(row["state"])
    await command(row, "resume")
    assert roleplay.panel(row["state"])["id"] == "greeting-2"
    assert not row["state"]["pendingInstruction"]
    await command(row, "panel_ready", panelId="greeting-2")
    assert row["state"]["roleplayPlayback"] == "greeting-2"


@pytest.mark.asyncio
async def test_existing_session_keeps_normal_path_when_pilot_is_enabled(session):
    row = await session(pilot=False)
    get_settings().classroom_roleplay_pilot_enabled = True
    resumed = await service.start(
        "user",
        Start(sessionId=row["id"], lessonId=roleplay.LESSON_ID, contentVersion="0.2.0"),
    )
    assert "roleplay" not in resumed["state"]
