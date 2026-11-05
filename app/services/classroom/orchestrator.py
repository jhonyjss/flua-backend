"""Pure transitions. Questions never count as attempts; audio delivery is separate."""

import json
from copy import deepcopy
from pathlib import Path

from app.schemas.classroom import TurnDecision

PERSONA = (Path(__file__).parents[1] / "prompts/flua_teacher_v2.md").read_text()


def initial(plan: dict) -> dict:
    return {
        "status": "paused",
        "mode": "lesson",
        "language": "pt-BR",
        "replyLanguage": "pt-BR",
        "index": 0,
        "stage": "repetir",
        "attempts": 0,
        "statuses": ["current"] + ["pending"] * (len(plan["items"]) - 1),
        "corrections": [],
        "finished": False,
        "anchor": None,
        "question": "",
        "pendingInstruction": "",
        "lastDelivered": "",
        "generation": 0,
    }


def pending(plan: dict, state: dict) -> str:
    item = plan["items"][state["index"]]
    if state["stage"] == "cena":
        return "Continue a mini-cena no ponto interrompido; faça uma fala de personagem em inglês e espere."
    if state["stage"] == "memoria":
        return "Peça uma frase da aula de memória, sem dar a resposta."
    if state["stage"] == "sozinho":
        return (
            item["cue"]
            or f"Peça uma frase própria usando a estrutura de {item['english']}, sem dar a resposta."
        )
    return f"Peça para repetir: {item['english']}."


def teach(plan: dict, state: dict) -> str:
    item = plan["items"][state["index"]]
    grammar = plan.get("grammar") if state["index"] == 0 else None
    return (
        "Conte uma pequena situação e explique o conceito com calma. "
        f"Dados do conteúdo: {json.dumps({'item': item, 'grammar': grammar}, ensure_ascii=False)}. "
        + pending(plan, state)
    )


def instructions(
    plan: dict, state: dict, action: str, *, teaching_skill: str = ""
) -> str:
    return (
        PERSONA
        + f"\nIdioma de conversa: {state['replyLanguage']}.\n"
        + (f"\nDidática da aula:\n{teaching_skill}\n" if teaching_skill else "")
        + "Estado e conteúdo confiável:\n"
        + json.dumps({"plan": plan, "state": state}, ensure_ascii=False)
        + "\nAção deste turno: "
        + action
    )


def transition(plan: dict, current: dict, decision: TurnDecision) -> dict:
    s = deepcopy(current)
    if s["finished"] or s["status"] in ("completed", "expired", "ended"):
        return s
    s["replyLanguage"] = s["language"]
    if decision.explicit_language_request and decision.language_request != "none":
        s["replyLanguage"] = decision.language_request
        if decision.language_scope == "session":
            s["language"] = decision.language_request
    action = pending(plan, s)
    if decision.intent == "stop":
        s.update(status="ended", pendingInstruction="", generation=s["generation"] + 1)
        return s
    if decision.intent == "pause":
        s.update(status="paused", pendingInstruction="", generation=s["generation"] + 1)
        return s
    if decision.intent in ("question", "unclear") or decision.needs_clarification:
        if s["anchor"] is None:
            s["anchor"] = {
                "index": s["index"],
                "stage": s["stage"],
                "attempts": s["attempts"],
                "pending": s.get("interruptedInstruction") or action,
            }
        s["question"] = decision.question_summary
        s["mode"] = (
            "clarification"
            if decision.needs_clarification or decision.intent == "unclear"
            else "question"
        )
        action = (
            "Faça uma pergunta específica para esclarecer a dúvida. Não avalie nem avance."
            if s["mode"] == "clarification"
            else "Responda à dúvida com calma usando o contexto da aula. Depois faça uma ponte e retome: "
            + s["anchor"]["pending"]
        )
    elif decision.intent == "answer_attempt" and s["mode"] == "clarification":
        # The pending question was ours: this is clarification, not exercise evidence.
        s["mode"] = "question"
        action = (
            "Use o esclarecimento para responder à dúvida. Depois retome: "
            + s["anchor"]["pending"]
        )
    elif decision.intent == "answer_attempt":
        s["mode"], s["anchor"], s["question"] = "lesson", None, ""
        correct = decision.result == "correct"
        if s["stage"] == "memoria":
            s.update(finished=True, status="completed")
            action = "Finalize com um ponto forte e uma sugestão baseada no que o aluno fez. Não faça perguntas."
        elif s["stage"] == "cena":
            s["attempts"] += 1
            if s["attempts"] >= 2:
                s.update(stage="memoria", attempts=0)
            action = pending(plan, s)
        else:
            if not correct:
                s["attempts"] += 1
                if decision.correction:
                    s["corrections"].append(
                        {
                            "itemId": plan["items"][s["index"]]["id"],
                            "correct": decision.correction,
                        }
                    )
            if correct or s["attempts"] >= 2:
                if s["stage"] == "repetir":
                    s.update(stage="sozinho", attempts=0)
                    action = pending(plan, s)
                else:
                    s["statuses"][s["index"]] = "reached" if correct else "practised"
                    if s["index"] + 1 < len(plan["items"]):
                        s["index"] += 1
                        s["statuses"][s["index"]] = "current"
                        s.update(stage="repetir", attempts=0)
                        action = teach(plan, s)
                    else:
                        s.update(stage="cena", attempts=0)
                        action = "Proponha uma mini-cena curta com as frases da aula e faça a primeira fala de personagem. Espere."
            else:
                action = "Dê uma pista sobre um erro por vez, sem dar a resposta; espere nova tentativa."
            action = (
                "Elogie especificamente. "
                if correct
                else "Acolha a tentativa e corrija com gentileza. "
            ) + action
    elif decision.intent == "language_request":
        action = (
            "Confirme brevemente a mudança. "
            if decision.explicit_language_request
            else "Pergunte se o aluno quer mudar o idioma da conversa; não mude ainda. "
        ) + action
    elif decision.intent == "repeat_request":
        action = "Repita a explicação mais devagar, com outro exemplo. " + action
    s["pendingInstruction"] = action
    s["generation"] += 1
    return s


def delivered(current: dict) -> dict:
    s = deepcopy(current)
    s["lastDelivered"] = s["pendingInstruction"]
    s["pendingInstruction"] = ""
    s["interruptedInstruction"] = ""
    if s["mode"] in ("question", "resuming"):
        s.update(mode="lesson", anchor=None, question="")
    return s
