"""Asks an LLM to list contradictions, repetitions and rules without input in each mode's assembled prompt
(the OpenAI Realtime prompting guide's advice). A reading aid for the rewrite, not a pass/fail check."""
from app.services import anthropic_client
from evals.flua.cases import TOPIC, free, guided, lesson
from evals.flua.judge import JUDGE_MODEL
from evals.flua.runner import build_session

MODES = {
    "lesson": {"request": lesson()},
    "guided_lesson": {"request": guided()},
    "free_practice": {
        "request": free(topic=TOPIC, reviewPhrases=[{"english": "Good morning", "portuguese": "Bom dia"}]),
        "mistakes": [{"said": "I have 30 years", "natural": "I'm 30", "tip": "idade usa to be"}],
    },
}

RUNTIME = {
    "lesson": "Turno controlado pelo cliente: ela só fala quando o app pede e não pode ser interrompida. Depois "
              "de cada fala do aluno o app força a ferramenta registrar_meta e responde com o próximo passo.",
    "guided_lesson": "Turno controlado pelo cliente: ela só fala quando o app pede e não pode ser interrompida. "
                     "Depois de cada fala do aluno o app força a ferramenta registrar_resultado e responde com o "
                     "próximo passo.",
    "free_practice": "No site o turno é controlado pelo cliente (ela só fala quando o app pede); no app o servidor "
                     "responde sozinho e o aluno pode interrompê-la. Não há ferramenta.",
}

SYSTEM = (
    "Você revisa o prompt de sistema de uma tutora de inglês por voz (OpenAI Realtime, modelo speech-to-speech: "
    "ela ouve o áudio do aluno e recebe só estas instruções e as mensagens do app; não recebe transcrição, "
    "velocidade de fala, contagem de metas nem rótulos que não estejam no texto). Liste, em português:\n"
    "1. Contradições: duas regras que mandam coisas incompatíveis.\n"
    "2. Regras sem efeito: dependem de um dado ou de um evento que ela nunca recebe ou que o modo torna "
    "impossível.\n"
    "3. Repetições: a mesma regra dita mais de uma vez.\n"
    "Para cada item, cite literalmente os trechos e explique em 1 frase por que importa. Não sugira regras novas."
)


async def audit(mode: str) -> str:
    _, config = build_session(MODES[mode])
    message = f"Como este modo roda: {RUNTIME[mode]}\n\nPrompt ({len(config['instructions'])} caracteres):\n\n" \
              f"{config['instructions']}"
    return await anthropic_client.complete(SYSTEM, message, max_tokens=4000, temperature=0.0, model=JUDGE_MODEL)
