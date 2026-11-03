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
from evals.flua.judge import JudgeError, judge
from evals.flua.runner import regressions, report, run_all, summary
from evals.flua.session import connect

HERE = Path(__file__).parent
BASELINE = HERE / "baseline.json"
RESULTS = HERE / "results"


def _keys() -> str:
    settings = get_settings()
    missing = [name for name, value in (("OPENAI_API_KEY", settings.openai_api_key),
                                        ("ANTHROPIC_API_KEY", settings.anthropic_api_key)) if not value]
    if missing:
        sys.exit(f"Defina {' e '.join(missing)} (no ambiente ou no .env do backend).")
    return settings.openai_api_key


async def _run(args: argparse.Namespace) -> int:
    api_key = _keys()
    cases = [case for case in CASES
             if (not args.case or case["id"] in args.case)
             and (not args.mode or case["request"]["mode"] == args.mode)]
    if not cases:
        sys.exit("Nenhum caso com esses filtros.")

    @asynccontextmanager
    async def open_session(model: str):
        async with connect(model, api_key) as session:
            yield session

    print(f"{len(cases)} casos × {args.runs} rodadas")
    try:
        results = await run_all(cases, runs=args.runs, connect=open_session, judge=judge,
                                concurrency=args.concurrency)
    except JudgeError as err:
        sys.exit(f"O juiz falhou, nada foi gravado: {err}")
    current = report(results, runs=args.runs)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(current, ensure_ascii=False, indent=2))
    print(summary(current))
    print(f"resultado: {out}")

    if args.save_baseline:
        BASELINE.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n")
        print(f"baseline salvo: {BASELINE}")
        return 0
    if BASELINE.exists():
        problems = regressions(current, json.loads(BASELINE.read_text()))
        print("contra o baseline: " + ("sem regressão" if not problems else "REGRESSÃO"))
        for problem in problems:
            print(f"  - {problem}")
        return 1 if problems else 0
    return 0


async def _audit(args: argparse.Namespace) -> int:
    _keys()
    for mode in [args.mode] if args.mode else list(audit_mod.MODES):
        print(f"\n## {mode}\n")
        print(await audit_mod.audit(mode))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.flua")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="roda os casos e compara com o baseline")
    run.add_argument("--mode", choices=["lesson", "guided_lesson", "free_practice"])
    run.add_argument("--case", action="append", help="id do caso (repetível)")
    run.add_argument("--runs", type=int, default=3)
    run.add_argument("--concurrency", type=int, default=4)
    run.add_argument("--save-baseline", action="store_true", help="grava este resultado como baseline")
    audit = sub.add_parser("audit", help="lista conflitos no prompt montado de cada modo")
    audit.add_argument("--mode", choices=list(audit_mod.MODES))
    args = parser.parse_args()
    return asyncio.run(_run(args) if args.command == "run" else _audit(args))


if __name__ == "__main__":
    sys.exit(main())
