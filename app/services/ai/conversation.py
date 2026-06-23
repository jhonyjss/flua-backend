"""Conversation response — port of server/api/ai/conversation-response.post.ts."""
from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from app.schemas.ai import ConversationHistoryItem, ConversationResponseRequest, NpcCharacter
from app.services.anthropic_client import complete

_DATA_DIR = Path(__file__).resolve().parent / "data"
INTEREST_LABELS = {
    "conversation": "everyday conversation and social situations",
    "business": "business English, work, career, and professional topics",
    "travel": "travel, tourism, cultures, and exploring the world",
    "exam": "academic English, exams (IELTS/TOEFL), and study topics",
    "entertainment": "movies, music, series, pop culture, and entertainment",
    "kids": "education, parenting, children, and family topics",
}


@lru_cache(maxsize=1)
def _load_prompt_data() -> dict:
    scenarios = json.loads((_DATA_DIR / "scenario_prompts.json").read_text(encoding="utf-8"))
    constants = json.loads((_DATA_DIR / "conversation_constants.json").read_text(encoding="utf-8"))
    return {"scenarios": scenarios, **constants}


def _sanitize_npc(npc: NpcCharacter) -> NpcCharacter:
    return NpcCharacter(
        name=(npc.name or "Flua").strip()[:80] or "Flua",
        role=(npc.role or "English tutor").strip()[:120] or "English tutor",
        personality=(npc.personality or "warm and encouraging").strip()[:300] or "warm and encouraging",
    )


def _no_repeat_block(history: list[ConversationHistoryItem]) -> str:
    questions: list[str] = []
    for msg in history:
        if msg.role != "npc":
            continue
        for q in re.findall(r"[^.!?]*\?", msg.message):
            q = q.strip()
            if len(q) > 5:
                questions.append(q)
    if not questions:
        return ""
    lines = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
    return (
        "\n⛔ QUESTIONS YOU ALREADY ASKED — DO NOT REPEAT ANY OF THESE (not even rephrased):\n"
        f"{lines}\n"
    )


def _lesson_context_block(req: ConversationResponseRequest) -> str:
    lc = req.lessonContext
    if not lc:
        return ""

    completed = ""
    if lc.completedTopics:
        completed = (
            "\nALREADY COMPLETED TOPICS (DO NOT revisit these):\n"
            + "\n".join(f"  ✅ {t}" for t in lc.completedTopics)
            + "\n\n⚠️ CRITICAL: The student already completed the topics above. Do NOT ask questions about them."
        )
    pending = ""
    if lc.pendingTopics:
        pending = "\nUPCOMING TOPICS (after current one is done):\n" + "\n".join(
            f"  ○ {t}" for t in lc.pendingTopics
        )
    progress = ""
    if lc.currentTopicNumber and lc.totalTopics:
        progress = f" (Goal {lc.currentTopicNumber} of {lc.totalTopics})"

    phrases = "\n".join(f'{i + 1}. "{p}"' for i, p in enumerate(lc.keyPhrases))
    block = f"""
=== LESSON PROGRESS ==={completed}

▶ CURRENT ACTIVE GOAL{progress}: "{lc.currentTopic}"
   (Portuguese: "{lc.currentTopicPt}")
{pending}

KEY PHRASES THE STUDENT MUST USE FOR THIS GOAL:
{phrases}

VOCABULARY: {", ".join(lc.vocabularyWords)}
GRAMMAR POINT (reference only — do NOT read this aloud): {lc.grammarPoint}

YOUR #1 JOB: Guide the student through the KEY PHRASES using the 4-PHASE METHOD.
When the student produces the target phrase correctly (same words and structure in the transcript), treat as EXACT_MATCH — celebrate with "Correct!" energy, do NOT ask to repeat slowly or say "Boa tentativa".
"""

    history = req.conversationHistory[-10:]
    student_msgs = [m.message.lower() for m in history if m.role == "user"]
    used: set[int] = set()
    for pi, phrase in enumerate(lc.keyPhrases):
        norm = re.sub(r"\[.*?\]", "", phrase).replace("...", "").lower().strip()
        if len(norm) < 3:
            continue
        words = [w for w in norm.split() if len(w) > 2]
        if any(sum(1 for w in words if w in msg) >= max(1, (len(words) + 1) // 2) for msg in student_msgs):
            used.add(pi)
    next_idx = next((i for i in range(len(lc.keyPhrases)) if i not in used), -1)
    target = lc.keyPhrases[next_idx] if next_idx >= 0 else (lc.keyPhrases[0] if lc.keyPhrases else "")
    if target:
        phase = (
            "FIRST phrase — Phase 1 warm-up, then Phase 2 demo, then Phase 3 question."
            if next_idx == 0
            else "Continuation — Phase 2 demo then Phase 3 question."
        )
        block += f'\n\n🎯 YOUR SINGLE FOCUS FOR THIS TURN: "{target}"\n{phase}'
    return block


def _teacher_mode_rule(req: ConversationResponseRequest) -> str:
    pe = req.portugueseExplanations
    if req.teacherMode:
        ack = '"Quase lá!", "Boa tentativa!"' if pe else '"Almost!", "Close!", "Good try!"'
        return (
            "TEACHER MODE — EXPLICIT CORRECTION (MANDATORY):\n"
            "Address the MOST important error (ONE per turn). Compare against target key phrase.\n"
            f"(a) Acknowledge warmly: {ack} — but NEVER use these if the student already said the phrase correctly.\n"
            '(b) Show correct sentence: "We say: [correct full sentence]"\n'
            "(c) Give a natural mini-scenario to try again — NOT repeat-after-me.\n"
            "If the student's words match the target phrase, celebrate and advance — do NOT correct."
        )
    explain = "explain briefly in Portuguese why" if pe else ""
    return (
        f"If the student makes a mistake, show the correct version, {explain}, and ask them to try again. "
        "If they already said the target phrase correctly, celebrate specifically and move forward."
    )


def build_system_prompt(req: ConversationResponseRequest) -> str:
    data = _load_prompt_data()
    npc = _sanitize_npc(req.npcCharacter)
    is_spanish = req.language == "es"
    default_scenario = "spanish-tutor" if is_spanish else "english-tutor"
    scenario_prompt = data["scenarios"].get(req.scenario) or data["scenarios"][default_scenario]
    level_key = req.userLevel
    level_instructions = (
        data["spanish_level_instructions"].get(level_key, "")
        if is_spanish
        else data["level_instructions"].get(level_key, "")
    )
    if req.portugueseExplanations:
        language_instructions = (
            data.get("portuguese_spanish_teaching") or ""
            if is_spanish
            else data.get("portuguese_teaching") or ""
        )
    else:
        language_instructions = (
            data.get("spanish_only") or ""
            if is_spanish and req.userLevel != "beginner"
            else (data.get("english_only") or "" if not is_spanish and req.userLevel == "beginner" else "")
        )

    interests = ""
    if req.scenario in ("free-conversation", "free-conversation-es") and req.studentInterests:
        labels = [INTEREST_LABELS.get(i, i) for i in req.studentInterests]
        interests = (
            "\n\n=== STUDENT PROFILE ===\n"
            f"Interests: {', '.join(labels)}. Lean toward these when topic is open."
        )

    focus = f"\nLEARNING FOCUS: Help the student practice {req.learningFocus}." if req.learningFocus else ""
    lesson_block = _lesson_context_block(req)
    no_repeat = _no_repeat_block(req.conversationHistory)

    if req.userLevel == "beginner":
        max_words = "3-5 sentences. ~35 words English; corrections may go to 50."
    elif req.userLevel == "intermediate":
        max_words = "3-5 sentences. MAX 50 words."
    else:
        max_words = "3-5 sentences. MAX 60 words."

    student_name = ""
    if req.studentName:
        student_name = f'\nSTUDENT NAME: "{req.studentName}". Use naturally.\n'

    acceptance = """
# Reconhecimento de acerto (CRÍTICO)
- Se a transcrição mostra a frase-alvo correta, trate como acerto imediato.
- NUNCA diga "Boa tentativa", "vamos devagar" ou "repita comigo" quando já acertou.
- Só comente pronúncia se atrapalhar compreensão; sotaque brasileiro é aceito.
"""

    rules_tail = f"""
=== CRITICAL RULES ===
1. Live video call — natural spoken dialogue only.
2. {max_words}
3. End with exactly ONE question (last sentence) about current objective.
4. {_teacher_mode_rule(req)}
5. NO emojis, bullets, or formatting.
6. Progress forward after correct answers.
{acceptance}
"""

    return (
        f"You are {npc.name}, {npc.role}.\nPersonality: {npc.personality}.\n"
        f"{student_name}{scenario_prompt}{interests}\n{level_instructions}\n"
        f"{language_instructions}{focus}{lesson_block}{no_repeat}{rules_tail}"
    )


def _max_tokens(req: ConversationResponseRequest) -> int:
    base = 380 if req.teacherMode else 260
    if req.userLevel == "intermediate":
        base = 400 if req.teacherMode else 280
    elif req.userLevel == "advanced":
        base = 420 if req.teacherMode else 310
    return int(base * 2.0) if req.portugueseExplanations else base


def _build_user_message(req: ConversationResponseRequest, safe_user: str) -> str:
    history = req.conversationHistory[-20:]
    recent = "\n".join(
        f"{'Student' if m.role == 'user' else 'You'}: {m.message}" for m in history
    )
    pt = (
        "- MODO PORTUGUÊS: reações em PT, frase-alvo e pergunta final em EN.\n"
        if req.portugueseExplanations
        else ""
    )
    if recent:
        return (
            f"Previous conversation:\n{recent}\n\n---\n\nStudent just said: \"{safe_user}\"\n\n"
            f"CRITICAL: If the student said the target phrase correctly, celebrate and advance. "
            f"Do NOT ask to repeat slowly.\n{pt}Ask ONE question as the LAST sentence."
        )
    name_note = (
        f'The student name is "{req.studentName}".'
        if req.studentName
        else "Ask for their name warmly if unknown."
    )
    return f'Student just started with: "{safe_user}"\n\n{name_note}\nGreet warmly and begin the lesson.'


def _sanitize_beginner(text: str) -> str:
    if len(text.split()) <= 35:
        return text
    q = re.search(r"([^.!?]*\?)\s*$", text)
    quote = re.search(r'"([^"]+)"', text)
    if quote and q:
        return f"Good try! {quote.group(1)}. {q.group(1)}"
    if q:
        return q.group(1)
    return " ".join(text.split()[:15])


async def run_conversation(req: ConversationResponseRequest) -> tuple[bool, str, str | None]:
    safe_user = req.userMessage.strip()[:2000]
    system = build_system_prompt(req)
    user_msg = _build_user_message(req, safe_user)
    try:
        raw = await complete(
            system,
            user_msg,
            max_tokens=_max_tokens(req),
            # Lowered 0.7 → 0.5 for more predictable, less "creative" tutoring
            # (reduces hallucination/inconsistency without sounding robotic).
            temperature=0.5,
        )
    except Exception as exc:
        return False, "", str(exc)

    response = raw.strip()
    if req.userLevel == "beginner" and not req.teacherMode and not req.portugueseExplanations:
        response = _sanitize_beginner(response)
    return True, response, None
