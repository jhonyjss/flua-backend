"""The server-owned Cumprimentos storyboard and presentation state."""

import json

LESSON_ID = "fund-u1-l1"
INTRO = "Bom, nesta aula vamos aprender a cumprimentar em inglês."

_STORYBOARD = (
    ("Flua", "Hello, Ana!", "Olá, Ana!", "Flua acena para Ana na entrada do curso."),
    ("Ana", "Hello, Flua!", "Olá, Flua!", "Ana retribui o cumprimento de Flua."),
    (
        "Flua",
        "I am Flua.",
        "Eu sou a Flua.",
        "Flua se apresenta com a mão sobre o peito.",
    ),
    ("Ana", "My name is Ana.", "Meu nome é Ana.", "Ana se apresenta para Flua."),
    (
        "Flua",
        "Goodbye, Ana!",
        "Tchau, Ana!",
        "Flua se despede de Ana na porta do curso.",
    ),
)


def initial() -> dict:
    return {
        "phase": "intro",
        "panelIndex": 0,
        "panelReady": False,
        "panels": [
            {
                "id": f"greeting-{index}",
                "speaker": speaker,
                "lineEn": line_en,
                "linePt": line_pt,
                "altPt": alt_pt,
            }
            for index, (speaker, line_en, line_pt, alt_pt) in enumerate(_STORYBOARD, 1)
        ],
    }


def panel(state: dict) -> dict | None:
    scene = state.get("roleplay")
    if scene and scene["phase"] == "panels":
        return scene["panels"][scene["panelIndex"]]
    return None


def queue(state: dict) -> None:
    """Only queue a scripted line once its image has been shown."""
    scene = state["roleplay"]
    if state["mode"] != "lesson" or state["pendingInstruction"]:
        return
    current = panel(state)
    if current and not scene["panelReady"]:
        return
    line = INTRO if current is None else current["lineEn"]
    state["roleplayPlayback"] = current["id"] if current else "intro"
    state["pendingInstruction"] = (
        f"Fale exatamente uma vez e depois pare: {json.dumps(line, ensure_ascii=False)}. "
        "Preserve o idioma original da fala. Não acrescente tradução, nome do personagem, "
        "pergunta, explicação ou despedida extra."
    )


def reset_connection(state: dict) -> None:
    """A new phone connection must show the current image again before speaking."""
    if not state.get("roleplay"):
        return
    state["roleplay"]["panelReady"] = False
    if state.get("roleplayPlayback"):
        state["pendingInstruction"] = ""
        state.pop("roleplayPlayback", None)


def advance(state: dict, playback: str | None) -> bool:
    """Advance only after the matching audio buffer drains. Return true at handoff."""
    scene = state["roleplay"]
    current = panel(state)
    if playback == "intro" and current is None:
        scene["phase"] = "panels"
    elif current and playback == current["id"]:
        scene["panelIndex"] += 1
        if scene["panelIndex"] == len(scene["panels"]):
            del state["roleplay"]
            return True
    else:
        return False
    scene["panelReady"] = False
    return False
