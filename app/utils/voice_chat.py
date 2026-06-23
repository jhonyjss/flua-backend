"""Sanitize voice chat turns (port of server/utils/voiceChatMessages.ts)."""
from __future__ import annotations

ALLOWED = {"user", "assistant"}


def sanitize_conversation_turns(messages: list[dict]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for msg in messages:
        role = str(msg.get("role") or "user").lower()
        if role in ("developer", "system"):
            continue
        if role not in ALLOWED:
            role = "user"
        content = msg.get("content")
        if content is None:
            continue
        text = str(content).strip()
        if not text:
            continue
        turns.append({"role": role, "content": text[:4000]})
    return turns
