"""python -m evals.flua run|audit — see evals/flua/README.md."""
import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from evals.flua import audit as audit_mod
from evals.flua.cases import CASES
from evals.flua.judge import JudgeError, ask, judge, judge_model
from evals.flua.runner import error_count, regressions, report, run_all, summary
from evals.flua.session import connect
from evals.flua.usage import USAGE

HERE = Path(__file__).parent
BASELINE = HERE / "baseline.json"
RESULTS = HERE / "results"


def _keys() -> str:
    settings = get_settings()
    needed = [("OPENAI_API_KEY", settings.openai_api_key)]
    if judge_model().startswith("claude"):
        needed.append(("ANTHROPIC_API_KEY", settings.anthropic_api_key))
    missing = [name for name, value in needed if not value]
    if missing:
        sys.exit(f"Defina {' e '.join(missing)} (no ambiente ou no .env do backend).")
    return settings.openai_api_key


async def _run(args: argparse.Namespace) -> int:
    api_key = _keys()
    if args.save_baseline and (args.case or args.mode):
        sys.exit("--save-baseline só com todos os casos: um baseline parcial deixaria os outros sem conferência.")
    cases = [case for case in CASES
             if (not args.case or case["id"] in args.case)
             and (not args.mode or case["request"]["mode"] == args.mode)]
    if not cases:
        sys.exit("Nenhum caso com esses filtros.")

    @asynccontextmanager
    async def open_session(model: str):
        async with connect(model, api_key) as session:
            yield session

    # A judge without credit or with a bad key would lose every judged run: find out before paying for the voice.
    try:
        await ask("Responda apenas: ok.", "ok?", max_tokens=500)
    except JudgeError as err:
        sys.exit(f"O juiz ({judge_model()}) não respondeu: {err}")

    print(f"{len(cases)} casos × {args.runs} rodadas")
    results = await run_all(cases, runs=args.runs, connect=open_session, judge=judge, concurrency=args.concurrency)
    current = report(results, runs=args.runs)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(current, ensure_ascii=False, indent=2))
    print(summary(current))
    print(f"resultado: {out}")
    print(f"tokens (juiz {judge_model()}):", *USAGE.lines(), sep="\n")

    if args.save_baseline and error_count(current):
        sys.exit("Baseline não gravado: há rodadas perdidas por erro da API ou do juiz. Rode de novo.")
    if args.save_baseline:
        BASELINE.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n")
        print(f"baseline salvo: {BASELINE}")
        return 0
    against = Path(args.against) if args.against else BASELINE
    if against.exists():
        problems = regressions(current, json.loads(against.read_text()))
        print(f"contra {against.name}: " + ("sem regressão" if not problems else "REGRESSÃO"))
        for problem in problems:
            print(f"  - {problem}")
        return 1 if problems else 0
    return 0


async def _audit(args: argparse.Namespace) -> int:
    _keys()
    for mode in [args.mode] if args.mode else list(audit_mod.MODES):
        print(f"\n## {mode}\n")
        try:
            print(await audit_mod.audit(mode))
        except JudgeError as err:
            sys.exit(f"A auditoria falhou: {err}")
    print("tokens:", *USAGE.lines(), sep="\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.flua")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="roda os casos e compara com o baseline")
    run.add_argument("--mode", choices=["lesson", "guided_lesson", "free_practice"])
    run.add_argument("--case", action="append", help="id do caso (repetível)")
    # The baseline's run count by default: results only compare at the same count.
    run.add_argument("--runs", type=int, default=json.loads(BASELINE.read_text())["runs"] if BASELINE.exists() else 5)
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--save-baseline", action="store_true", help="grava este resultado como baseline")
    run.add_argument("--against", help="compara com este resultado em vez do baseline.json (ex.: o prompt "
                                       "antigo rodado na mesma sessão)")
    audit = sub.add_parser("audit", help="lista conflitos no prompt montado de cada modo")
    audit.add_argument("--mode", choices=list(audit_mod.MODES))
    args = parser.parse_args()
    return asyncio.run(_run(args) if args.command == "run" else _audit(args))


if __name__ == "__main__":
    sys.exit(main())
