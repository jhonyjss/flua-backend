"""A text-only Realtime session over WebSocket: production's model, instructions and tools, with the learner's
turns sent as text (the site's typed answers take this path too). Audio-only behaviour (accent, noise, VAD) is
out of reach here."""
import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

REALTIME_URL = "wss://api.openai.com/v1/realtime?model={model}"
EVENT_TIMEOUT_S = 60.0


class Connection(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str: ...


class SessionError(RuntimeError):
    """The Realtime API answered with an error or an unfinished response."""


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: str

    @property
    def args(self) -> Any:
        try:
            return json.loads(self.arguments)
        except json.JSONDecodeError:
            return None


@dataclass
class Reply:
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)


def text_session(config: dict) -> dict:
    """The minted session config, adapted to text: no audio either way and no turn detection (the eval
    sends each turn itself). The model stays in the URL; session.update can't change it."""
    session = {key: value for key, value in config.items() if key not in ("model", "audio")}
    session["output_modalities"] = ["text"]
    return session


def parse_response(event: dict) -> Reply:
    response = event.get("response") or {}
    if response.get("status") != "completed":
        raise SessionError(f"resposta {response.get('status')}: {response.get('status_details')}")
    reply = Reply()
    for item in response.get("output") or []:
        if item.get("type") == "function_call":
            reply.calls.append(ToolCall(item.get("call_id", ""), item.get("name", ""), item.get("arguments", "")))
        elif item.get("type") == "message":
            reply.text += "".join(
                part.get("text") or part.get("transcript") or ""
                for part in item.get("content") or []
            )
    return reply


class TextSession:
    def __init__(self, conn: Connection):
        self._conn = conn
        self._calls = 0
        self.last_call_id = ""

    async def _send(self, event: dict) -> None:
        await self._conn.send(json.dumps(event))

    async def _until(self, event_type: str) -> dict:
        while True:
            event = json.loads(await asyncio.wait_for(self._conn.recv(), EVENT_TIMEOUT_S))
            if event.get("type") == "error":
                raise SessionError(json.dumps(event.get("error"), ensure_ascii=False))
            if event.get("type") == event_type:
                return event

    async def configure(self, session: dict) -> None:
        await self._send({"type": "session.update", "session": session})
        await self._until("session.updated")

    async def _item(self, item: dict) -> None:
        await self._send({"type": "conversation.item.create", "item": item})

    async def learner(self, text: str) -> None:
        await self._item({"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]})

    async def flua(self, text: str) -> None:
        """Something she said earlier in the class."""
        await self._item({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})

    async def system(self, text: str) -> None:
        await self._item({"type": "message", "role": "system", "content": [{"type": "input_text", "text": text}]})

    async def past_call(self, name: str, arguments: dict) -> None:
        """An evaluation she reported earlier, so a case can start right at the tool's answer."""
        self._calls += 1
        self.last_call_id = f"call_eval_{self._calls}"
        await self._item({
            "type": "function_call", "call_id": self.last_call_id, "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        })

    async def respond(self, **response: Any) -> Reply:
        await self._send({"type": "response.create", **({"response": response} if response else {})})
        reply = parse_response(await self._until("response.done"))
        if reply.calls:
            self.last_call_id = reply.calls[0].call_id
        return reply

    async def answer_tool_silently(self, output: str) -> None:
        await self._item({"type": "function_call_output", "call_id": self.last_call_id, "output": output})

    async def answer_tool(self, output: str, **response: Any) -> Reply:
        await self.answer_tool_silently(output)
        return await self.respond(**response)


@asynccontextmanager
async def connect(model: str, api_key: str) -> AsyncIterator[TextSession]:
    import websockets

    async with websockets.connect(
        REALTIME_URL.format(model=model),
        additional_headers={"Authorization": f"Bearer {api_key}"},
        max_size=None,
    ) as ws:
        yield TextSession(ws)
