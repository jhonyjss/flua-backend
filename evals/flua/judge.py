"""Claude judges what code can't: whether a reply meets each rubric criterion, quoting the words that show it.
A model from another family than the one under test, so it doesn't favour its own phrasing."""
import json
import os

from app.services import anthropic_client

JUDGE_MODEL = os.environ.get("FLUA_EVAL_JUDGE_MODEL", "claude-opus-5-5")

SYSTEM = (
    "Você avalia falas da Flua, tutora de inglês por voz para brasileiros. Para cada critério, decida se a "
    "fala o cumpre e cite o trecho da fala que mostra isso (ou diga o que falta). Julgue só a fala contra o "
    "critério, de forma literal; não cobre nada além dele. Responda só com JSON: "
    '{"criterios": [{"n": 1, "passou": true, "trecho": "..."}]}'
)


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
    text = await anthropic_client.complete(
        SYSTEM, judge_message(reply, criteria, context), max_tokens=800, temperature=0.0, model=JUDGE_MODEL,
    )
    try:
        verdict = anthropic_client.extract_json(text)
    except ValueError:
        return [f"juiz respondeu sem JSON: {json.dumps(text[:160], ensure_ascii=False)}"]
    return failures_from_verdict(verdict, criteria)
