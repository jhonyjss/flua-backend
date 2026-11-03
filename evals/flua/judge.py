"""The judge: decides what code can't (whether a reply meets each rubric criterion), quoting the words that show
it. Defaults to an OpenAI text model; a Claude model (FLUA_EVAL_JUDGE_MODEL=claude-…) is preferable, being of
another family than the voice model under test, when the Anthropic account has credit."""
import json
import os

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.http import http_client
from app.services import anthropic_client
from app.services.openai_client import extract_response_text
from evals.flua.usage import USAGE

JUDGE_MODEL = os.environ.get("FLUA_EVAL_JUDGE_MODEL", "gpt-5.5")

SYSTEM = (
    "Você avalia falas da Flua, tutora de inglês por voz para brasileiros. Para cada critério, decida se a "
    "fala o cumpre e cite o trecho da fala que mostra isso (ou diga o que falta). Julgue só a fala contra o "
    "critério, de forma literal; não cobre nada além dele. Responda só com JSON: "
    '{"criterios": [{"n": 1, "passou": true, "trecho": "..."}]}'
)

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {"criterios": {"type": "array", "items": {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "passou": {"type": "boolean"}, "trecho": {"type": "string"}},
        "required": ["n", "passou", "trecho"],
        "additionalProperties": False,
    }}},
    "required": ["criterios"],
    "additionalProperties": False,
}


class JudgeError(RuntimeError):
    """The judge itself failed (no credit, bad key, outage): such a run says nothing about the prompt, so it
    stops the eval instead of counting as a failed case."""


async def _openai(system: str, message: str, *, max_tokens: int, schema: dict | None) -> str:
    settings = get_settings()
    payload: dict = {
        "model": JUDGE_MODEL,
        "input": [{"role": "system", "content": system}, {"role": "user", "content": message}],
        "max_output_tokens": max_tokens,
        "reasoning": {"effort": "low"},
        "store": False,
    }
    if schema:
        payload["text"] = {"format": {"type": "json_schema", "name": "veredito", "schema": schema, "strict": True}}
    async with http_client(timeout=120.0) as client:
        res = await client.post(
            "https://api.openai.com/v1/responses", json=payload,
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
    if res.status_code != 200:
        raise JudgeError(f"OpenAI {res.status_code}: {res.text[:200]}")
    data = res.json()
    USAGE.add(JUDGE_MODEL, data.get("usage"))
    return extract_response_text(data)


async def ask(system: str, message: str, *, max_tokens: int = 4000, schema: dict | None = None) -> str:
    """One completion from the judge model; the audit uses it too."""
    if not JUDGE_MODEL.startswith("claude"):
        return await _openai(system, message, max_tokens=max_tokens, schema=schema)
    try:
        return await anthropic_client.complete(system, message, max_tokens=max_tokens, temperature=0.0,
                                               model=JUDGE_MODEL)
    except HTTPException as err:
        raise JudgeError(str(err.detail)) from err


def judge_message(reply: str, criteria: list[str], context: str) -> str:
    listed = "\n".join(f"{n}. {criterion}" for n, criterion in enumerate(criteria, 1))
    return f"Contexto da aula:\n{context}\n\nFala da Flua:\n{reply}\n\nCritérios:\n{listed}"


def failures_from_verdict(verdict: dict, criteria: list[str]) -> list[str]:
    """Each criterion the judge failed, or left out, with its quote."""
    by_number = {item.get("n"): item for item in verdict.get("criterios") or [] if isinstance(item, dict)}
    failures = []
    for n, criterion in enumerate(criteria, 1):
        item = by_number.get(n)
        if item is None:
            failures.append(f"juiz não avaliou: {criterion}")
        elif item.get("passou") is not True:
            failures.append(f"{criterion} — {item.get('trecho', '')}")
    return failures


async def judge(reply: str, criteria: list[str], context: str) -> list[str]:
    text = await ask(SYSTEM, judge_message(reply, criteria, context), max_tokens=2000, schema=VERDICT_SCHEMA)
    try:
        verdict = anthropic_client.extract_json(text)
    except ValueError:
        return [f"juiz respondeu sem JSON: {json.dumps(text[:160], ensure_ascii=False)}"]
    return failures_from_verdict(verdict, criteria)
