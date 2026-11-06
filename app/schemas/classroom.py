"""Server-owned classroom v2 contracts. No client-supplied prompts or plans."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Start(Contract):
    sessionId: UUID
    lessonId: str = Field(pattern=r"^[a-z0-9-]+$", max_length=64)
    contentVersion: str = Field(max_length=32)


class Connection(Contract):
    connectionAttemptId: UUID
    sdpOffer: str = Field(min_length=10, max_length=65536)


class Command(Contract):
    commandId: UUID
    expectedVersion: int = Field(ge=0)
    type: Literal[
        "pause",
        "resume",
        "stop",
        "set_language",
        "text_turn",
        "ready",
        "interrupt",
        "disconnect",
        "panel_ready",
        "roleplay_help",
    ]
    text: str = Field(default="", max_length=2000)
    language: Literal["pt-BR", "en-US"] | None = None
    scope: Literal["session", "turn"] = "session"
    panelId: str | None = Field(default=None, pattern=r"^[a-z0-9-]+$", max_length=64)

    @model_validator(mode="after")
    def valid_payload(self):
        if self.type == "set_language" and self.language is None:
            raise ValueError("set_language requires language")
        if self.type == "text_turn" and not self.text.strip():
            raise ValueError("text_turn requires text")
        if self.type == "panel_ready" and self.panelId is None:
            raise ValueError("panel_ready requires panelId")
        if self.panelId is not None and self.type != "panel_ready":
            raise ValueError("panelId is only valid for panel_ready")
        return self


class TurnDecision(Contract):
    intent: Literal[
        "answer_attempt",
        "question",
        "language_request",
        "repeat_request",
        "pause",
        "resume",
        "stop",
        "unclear",
    ]
    observed_language: Literal["pt", "en", "mixed", "unclear"]
    language_request: Literal["none", "pt-BR", "en-US"] = "none"
    language_scope: Literal["session", "turn"] = "session"
    explicit_language_request: bool = False
    needs_clarification: bool = False
    question_summary: str = Field(default="", max_length=600)
    result: Literal["correct", "partial", "incorrect"] | None = None
    correction: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def valid_attempt(self):
        if self.intent == "answer_attempt" and self.result is None:
            raise ValueError("An attempt requires result")
        return self
