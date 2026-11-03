"""Runs the cases against the production session config and scores them (docs: evals/flua/README.md)."""
import asyncio
import json
import subprocess
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from app.schemas.realtime import RealtimeSessionRequest
from app.services.realtime import build_tutor_instructions_from_request, session_config
from evals.flua.checks import check_reply, check_tool
from evals.flua.session import Reply, SessionError, TextSession, text_session

Connect = Callable[[str], AbstractAsyncContextManager[TextSession]]
Judge = Callable[[str, list[str], str], Awaitable[list[str]]]


@dataclass
class CaseResult:
    id: str
    category: str
    mode: str
    model: str
    runs: int
    passes: int = 0
    # Failures of each failed run, and the transcript of the last failed one, to read why.
    failures: list[list[str]] = field(default_factory=list)
    transcript: list[str] = field(default_factory=list)


def build_session(case: dict) -> tuple[RealtimeSessionRequest, dict]:
    req = RealtimeSessionRequest(**case["request"])
    instructions = build_tutor_instructions_from_request(req, None, case.get("mistakes") or [])
    return req, session_config(req, None, instructions)


async def _history(session: TextSession, history: list) -> list[str]:
    transcript = []
    for n, entry in enumerate(history):
        kind = entry[0]
        if kind == "flua":
            await session.flua(entry[1])
            transcript.append(f"Flua: {entry[1]}")
        elif kind == "aluno":
            await session.learner(entry[1])
            transcript.append(f"Aluno: {entry[1]}")
        elif kind == "call":
            await session.past_call(entry[1], entry[2])
            transcript.append(f"[{entry[1]} {json.dumps(entry[2], ensure_ascii=False)}]")
            # A call the class already moved past was answered; the last one is answered by the case.
            if n < len(history) - 1:
                await session.answer_tool_silently("Registrado.")
    return transcript


async def run_once(case: dict, config: dict, session: TextSession, judge: Judge) -> tuple[list[str], list[str]]:
    """One pass of the case's steps; returns (failures, transcript)."""
    tools = bool(config.get("tools"))
    # With a tool in the session, the clients ask for every reply that isn't an evaluation with tool_choice
    # "none" (useRealtimeVoice.triggerResponse).
    plain = {"tool_choice": "none"} if tools else {}
    language = case["request"].get("language", "en")
    await session.configure(text_session(config))
    transcript = await _history(session, case.get("history", []))
    failures: list[str] = []
    replies: list[Reply] = []

    for step in case["steps"]:
        reply: Reply | None = None
        if "say" in step:
            await session.learner(step["say"])
            transcript.append(f"Aluno: {step['say']}")
        elif "evaluate" in step:
            await session.system(step["evaluate"])
            reply = await session.respond(
                tool_choice={"type": "function", "name": step["tool"]}, output_modalities=["text"],
            )
            transcript.append(f"[{step['tool']} {' | '.join(call.arguments for call in reply.calls)}]")
        elif "tool_output" in step:
            reply = await session.answer_tool(step["tool_output"], **plain)
        elif "instruct" in step:
            await session.system(step["instruct"])
            reply = await session.respond(**plain)
        elif step.get("respond") or step.get("open"):
            reply = await session.respond(**plain)
        if reply is None:
            continue

        expect = step.get("expect", {})
        if "evaluate" in step:
            failures += check_tool(reply, expect.get("tool", {"name": step["tool"]}))
            continue
        transcript.append(f"Flua: {reply.text}")
        replies.append(reply)
        failures += check_reply(reply, expect.get("reply", {}), language=language)
        if expect.get("rubric"):
            failures += await judge(reply.text, expect["rubric"], "\n".join(transcript[:-1]) or "(início da aula)")

    if case.get("across", {}).get("some_reply_without_question") and all(
        reply.text.rstrip().endswith("?") for reply in replies
    ):
        failures.append("todas as falas terminaram em pergunta")
    return failures, transcript


async def run_case(case: dict, *, runs: int, connect: Connect, judge: Judge) -> CaseResult:
    req, config = build_session(case)
    result = CaseResult(case["id"], case["category"], req.mode, config["model"], runs)
    for _ in range(runs):
        try:
            async with connect(config["model"]) as session:
                failures, transcript = await run_once(case, config, session, judge)
        except (SessionError, TimeoutError, OSError) as err:
            failures, transcript = [f"erro da sessão: {err}"], []
        if failures:
            result.failures.append(failures)
            result.transcript = transcript
        else:
            result.passes += 1
    return result


async def run_all(cases: list[dict], *, runs: int, connect: Connect, judge: Judge,
                  concurrency: int = 4) -> list[CaseResult]:
    gate = asyncio.Semaphore(concurrency)

    async def one(case: dict) -> CaseResult:
        async with gate:
            result = await run_case(case, runs=runs, connect=connect, judge=judge)
            print(f"  {result.passes}/{result.runs}  {result.id}", flush=True)
            return result

    return list(await asyncio.gather(*(one(case) for case in cases)))


def backend_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def report(results: list[CaseResult], *, runs: int) -> dict:
    return {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "backend": backend_commit(),
        "runs": runs,
        "cases": [asdict(result) for result in results],
    }


def by_category(report_: dict) -> dict[str, tuple[int, int]]:
    """Passes and runs per category."""
    totals: dict[str, tuple[int, int]] = {}
    for case in report_["cases"]:
        passes, runs = totals.get(case["category"], (0, 0))
        totals[case["category"]] = (passes + case["passes"], runs + case["runs"])
    return totals


def regressions(current: dict, baseline: dict) -> list[str]:
    """The 2c acceptance rule: no category passes fewer runs than the baseline, and no case that passed every
    run in the baseline now passes fewer than 2 of 3 (scaled to the run count). Cases only one side ran are
    left out, so a partial run is compared on what it ran."""
    if current["runs"] != baseline["runs"]:
        return [f"rodadas diferentes: {current['runs']} contra {baseline['runs']} no baseline"]
    ran = {case["id"] for case in current["cases"]}
    old = {case["id"]: case for case in baseline["cases"] if case["id"] in ran}
    shared = {**baseline, "cases": list(old.values())}
    problems = []
    now_totals, old_totals = by_category(current), by_category(shared)
    for category, (passes, _) in sorted(old_totals.items()):
        now = now_totals.get(category, (0, 0))[0]
        if now < passes:
            problems.append(f"categoria {category}: {now} contra {passes} no baseline")
    floor = -(-2 * current["runs"] // 3)  # 2 of 3, rounded up
    for case in current["cases"]:
        before = old.get(case["id"])
        if before and before["passes"] == before["runs"] and case["passes"] < floor:
            problems.append(f"caso {case['id']}: {case['passes']}/{case['runs']} (passava {before['passes']}/{before['runs']})")
    return problems


def summary(report_: dict) -> str:
    lines = [f"backend {report_['backend']} · {report_['runs']} rodadas por caso"]
    for category, (passes, runs) in sorted(by_category(report_).items()):
        lines.append(f"  {category:24} {passes}/{runs}")
    total_passes = sum(case["passes"] for case in report_["cases"])
    total_runs = sum(case["runs"] for case in report_["cases"])
    lines.append(f"  {'total':24} {total_passes}/{total_runs}")
    failed = [case for case in report_["cases"] if case["passes"] < case["runs"]]
    for case in failed:
        first = case["failures"][0] if case["failures"] else []
        lines.append(f"  ✗ {case['id']} {case['passes']}/{case['runs']}: {'; '.join(first)[:240]}")
    return "\n".join(lines)

