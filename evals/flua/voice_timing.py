"""Audio timing of the app's guided lesson: how long the learner waits for Flua and how fast she speaks.

The text eval (evals/flua) can't see turn detection or speech. This replays real audio over the Realtime WebSocket
with production's session_config: a learner clip (macOS `say`, a Brazilian Portuguese voice speaking English) is
streamed in real time (40 ms chunks over a low noise floor), and then the client's steps run exactly as in the app
(flueai-app use-flua-voice.ts): transcription completed → system message + forced registrar_resultado (text) →
function_call_output + response.create(tool_choice none) → Flua speaks. Every step is timed on the wall clock, from
the end of the learner's speech.

Clips with a mid-sentence pause ("My name is… [900 ms] Pedro.") check that the turn is not cut (one commit).
Short complete answers ("I am Ana.") check the worst case of semantic_vad, which can wait up to its timeout.

    python -m evals.flua.voice_timing                  # 3 judged turns + VAD clips, 2 runs
    python -m evals.flua.voice_timing --runs 4 --only judged
    OPENAI_REALTIME_LESSON_VAD_EAGERNESS=low python -m evals.flua.voice_timing --only vad

Settings come from the environment like production's (OPENAI_REALTIME_LESSON_VAD_EAGERNESS,
OPENAI_REALTIME_GUIDED_VOICE_SPEED, ...). macOS only (needs `say`); costs a little (mini model, short audio).
"""
import argparse
import array
import asyncio
import base64
import json
import os
import random
import statistics
import subprocess
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.schemas.realtime import RealtimeSessionRequest
from app.services.realtime import build_tutor_instructions_from_request, session_config
from evals.flua.cases import PLAN, guided

HERE = Path(__file__).parent
RESULTS = HERE / "results"
CLIPS = RESULTS / "voice-clips"
RATE = 24000
CHUNK_S = 0.04
LEAD_S = 0.4
VOICES = {"l": "Luciana", "e": "Eddy (Portuguese (Brazil))"}

# What Flua said last, and the app's texts for the step (copies of guided-lesson-machine.ts, like cases.py).
TAUGHT_1 = "Para se apresentar, a gente diz: I am Ana — eu sou a Ana. Repete comigo: I am Ana."
TAUGHT_3 = "Quando conhece alguém, diga: Nice to meet you — prazer em te conhecer. Repete comigo: Nice to meet you."
ALONE_2 = "Agora é a sua vez: diga o seu nome para mim, em inglês."


def _context(n: int, stage: str) -> str:
    item = PLAN["items"][n - 1]
    head = f"Avalie a última fala do aluno no item {n} ({item['id']}), etapa {stage}:"
    if stage == "repetir":
        return f'{head} ele devia repetir "{item["english"]}".'
    return (f'{head} o pedido foi "{item["cue"]}" (modelo: {" / ".join(item["accepts"])}); vale qualquer frase '
            "correta que cumpra o pedido, com nomes e dados diferentes dos do exemplo.")


def _alone(n: int) -> str:
    english = PLAN["items"][n - 1]["english"]
    return (f'correto. Elogie em 1 frase curta. Etapa sua vez do item {n}: peça em português para ele dizer a frase '
            f'"{english}" trocando UMA informação (outro nome, país, número ou objeto, você escolhe e diz qual), sem '
            "dizer a resposta. PARE e espere.")


def _teach(n: int) -> str:
    item = PLAN["items"][n - 1]
    return (f'correto. Elogie em 1 frase curta. Agora ensine o item {n} ({item["id"]}): frase "{item["english"]}", '
            f'tradução "{item["portuguese"]}", nota: {item["note"]}. Peça para o aluno repetir e PARE.')


# name: (say text, voice, Flua's last line, evaluation context or None for a VAD-only clip, tool answer)
JUDGED = {
    "i_am_ana": ("I am Ana.", "l", TAUGHT_1, _context(1, "repetir"), _alone(1)),
    "nice": ("Nice to meet you.", "l", TAUGHT_3, _context(3, "repetir"), _alone(3)),
    "my_name": ("My name is Pedro.", "l", ALONE_2, _context(2, "sozinho"), _teach(3)),
}
SHORT = {"iamana": "I am Ana.", "hello": "Hello!", "goodmorning": "Good morning.", "yes": "Yes.",
         "thanks": "Thank you.", "fine": "I'm fine, thanks.", "student": "I am a student.",
         "seeyou": "See you later.", "howareyou": "How are you?", "teacher": "She is a teacher."}
PAUSED = {
    "p_name900": ("My name is... [[slnc 900]] Pedro.", "l"),
    "p_name1000": ("My name is... [[slnc 1000]] Pedro.", "l"),
    "p_from800": ("I am... [[slnc 800]] from... [[slnc 800]] Brazil.", "l"),
    "p_from1100": ("I am... [[slnc 1100]] from Brazil.", "l"),
    "p_student900": ("I am a... [[slnc 900]] student.", "e"),
}
VAD_ONLY = {**{f"s_{k}_{v}": (text, v) for k, text in SHORT.items() for v in VOICES}, **PAUSED}


def _clip(name: str, text: str, voice: str) -> tuple[bytes, float]:
    """PCM16 24 kHz mono, and where the speech ends (s)."""
    path = CLIPS / f"{name}.wav"
    if not path.exists():
        CLIPS.mkdir(parents=True, exist_ok=True)
        rate = "140" if "slnc" in text else "150"
        subprocess.run(["say", "-v", VOICES[voice], "-r", rate, "-o", str(path), "--file-format=WAVE",
                        "--data-format=LEI16@24000", text], check=True)
    with wave.open(str(path)) as w:
        frames = w.readframes(w.getnframes())
    samples = array.array("h", frames)
    return frames, max(i for i, v in enumerate(samples) if abs(v) > 500) / RATE


def _noise(n: int) -> bytes:
    return array.array("h", (random.randint(-25, 25) for _ in range(n))).tobytes()


def production_config() -> dict:
    req = RealtimeSessionRequest(**guided(voice="marin"))
    return session_config(req, None, build_tutor_instructions_from_request(req))


async def one_turn(config: dict, name: str, key: str) -> dict:
    import websockets

    if name in JUDGED:
        text, voice, last_line, context, tool_answer = JUDGED[name]
    else:
        (text, voice), last_line, context, tool_answer = VAD_ONLY[name], ALONE_2, None, None
    pcm, speech_end = _clip(name, text, voice)
    t: dict = {}
    commits, heard, audio_bytes, spoken, verdict = 0, [], 0, "", None
    async with websockets.connect(f"wss://api.openai.com/v1/realtime?model={config['model']}",
                                  additional_headers={"Authorization": f"Bearer {key}"}, max_size=None) as ws:
        async def send(event: dict) -> None:
            await ws.send(json.dumps(event))

        await send({"type": "session.update", "session": {k: v for k, v in config.items() if k != "model"}})
        while json.loads(await ws.recv())["type"] != "session.updated":
            pass
        await send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": last_line}]}})
        stop = asyncio.Event()

        async def stream() -> None:
            chunk = int(RATE * CHUNK_S)
            data = _noise(int(RATE * LEAD_S)) + pcm
            end_sample = int(RATE * LEAD_S) + int(speech_end * RATE)
            start = time.monotonic()
            k = 0
            while not stop.is_set() and k * CHUNK_S < 30:
                first = k * chunk
                piece = data[first * 2:(first + chunk) * 2]
                piece += _noise(chunk - len(piece) // 2)
                await asyncio.sleep(max(0.0, start + k * CHUNK_S - time.monotonic()))
                await send({"type": "input_audio_buffer.append", "audio": base64.b64encode(piece).decode()})
                if first <= end_sample < first + chunk:
                    t["speech_end"] = time.monotonic() + (end_sample - first) / RATE
                k += 1

        streamer = asyncio.create_task(stream())
        deadline = time.monotonic() + 25
        try:
            while time.monotonic() < deadline:
                try:
                    event = json.loads(await asyncio.wait_for(ws.recv(), 2))
                except TimeoutError:
                    if context is None and heard and time.monotonic() - t["transcribed"] > 3:
                        break  # a second commit would have come by now: the turn was not cut
                    continue
                kind, now = event["type"], time.monotonic()
                if kind == "error":
                    raise RuntimeError(json.dumps(event.get("error")))
                if kind == "input_audio_buffer.speech_stopped":
                    t.setdefault("stopped", now)
                elif kind == "input_audio_buffer.committed":
                    commits += 1
                elif kind == "conversation.item.input_audio_transcription.completed":
                    t.setdefault("transcribed", now)
                    heard.append(event.get("transcript", "").strip())
                    if context and "eval_sent" not in t:
                        t["eval_sent"] = now
                        await send({"type": "conversation.item.create", "item": {
                            "type": "message", "role": "system", "content": [{"type": "input_text", "text": context}]}})
                        await send({"type": "response.create", "response": {
                            "tool_choice": {"type": "function", "name": "registrar_resultado"},
                            "output_modalities": ["text"]}})
                elif kind == "response.done":
                    calls = [o for o in event["response"].get("output", []) if o.get("type") == "function_call"]
                    if calls:
                        t["evaluated"] = now
                        verdict = json.loads(calls[0]["arguments"]).get("resultado")
                        await send({"type": "conversation.item.create", "item": {
                            "type": "function_call_output", "call_id": calls[0]["call_id"], "output": tool_answer}})
                        t["reply_sent"] = time.monotonic()
                        await send({"type": "response.create", "response": {"tool_choice": "none"}})
                    elif "reply_sent" in t:
                        break
                elif kind == "response.output_audio.delta":
                    t.setdefault("first_audio", now)
                    audio_bytes += len(base64.b64decode(event["delta"]))
                elif kind == "response.output_audio_transcript.delta":
                    spoken += event.get("delta", "")
        finally:
            stop.set()
            await streamer

    def ms(a: str, b: str) -> int | None:
        return round((t[b] - t[a]) * 1000) if a in t and b in t else None

    words = len([w for w in spoken.split() if any(c.isalnum() for c in w)])
    seconds = audio_bytes / 2 / RATE
    return {
        "clip": name, "commits": commits, "heard": " | ".join(heard), "verdict": verdict,
        "vad_ms": ms("speech_end", "stopped"), "stt_ms": ms("stopped", "transcribed"),
        "eval_ms": ms("eval_sent", "evaluated"), "first_audio_ms": ms("reply_sent", "first_audio"),
        "dead_air_ms": ms("speech_end", "first_audio"), "reply_s": round(seconds, 2) if seconds else None,
        "reply_words": words or None, "words_per_s": round(words / seconds, 2) if seconds else None,
        "reply": spoken.strip(),
    }


def summary(rows: list[dict]) -> str:
    lines = []
    for key in ("vad_ms", "stt_ms", "eval_ms", "first_audio_ms", "dead_air_ms", "reply_s", "reply_words",
                "words_per_s"):
        values = sorted(r[key] for r in rows if r.get(key) is not None and r["clip"] in JUDGED)
        if values:
            lines.append(f"  {key:15} mediana {statistics.median(values):>8} · média {statistics.mean(values):>8.2f} · "
                         f"máx {values[-1]:>8}  (n={len(values)}, falas avaliadas)")
    short = sorted(r["vad_ms"] for r in rows if r["clip"].startswith("s_") and r["vad_ms"] is not None)
    if short:
        p90 = short[int(0.9 * (len(short) - 1))]
        lines.append(f"  vad_ms (respostas curtas) mediana {statistics.median(short)} · média "
                     f"{statistics.mean(short):.0f} · p90 {p90} · máx {short[-1]} (n={len(short)})")
    paused = [r for r in rows if r["clip"] in PAUSED]
    if paused:
        cut = [f"{r['clip']} ({r['heard']})" for r in paused if r["commits"] > 1]
        lines.append(f"  pausas no meio da frase cortadas: {len(cut)}/{len(paused)}" + (f": {', '.join(cut)}" if cut else ""))
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.flua.voice_timing")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--only", choices=["judged", "vad"])
    args = parser.parse_args()
    key = os.environ.get("OPENAI_API_KEY") or get_settings().openai_api_key
    config = production_config()
    names = [*([] if args.only == "vad" else JUDGED), *([] if args.only == "judged" else VAD_ONLY)]
    print(config["model"], json.dumps(config["audio"]["input"]["turn_detection"]), config["audio"]["output"])
    rows = []
    for run in range(args.runs):
        for name in names:
            row = {"run": run, **await one_turn(config, name, key)}
            rows.append(row)
            print(json.dumps({k: v for k, v in row.items() if k != "reply"}, ensure_ascii=False), flush=True)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"voice-timing-{datetime.now(UTC):%Y%m%d-%H%M%S}.jsonl"
    out.write_text("".join(json.dumps({"config": config["audio"], **row}, ensure_ascii=False) + "\n" for row in rows))
    print(summary(rows), f"resultado: {out}", sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
