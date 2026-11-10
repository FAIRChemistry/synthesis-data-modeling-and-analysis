#!/usr/bin/env python3
"""Backfill the ``intermediate/`` folder for existing run(s).

The intermediate cleaned JSON (the per-record input the LLM sees) is generated
deterministically from the case inputs by ``case.iter_records()``. As long as the
cleaner and the inputs are unchanged, re-deriving them now reproduces what each
run fed the model. For each run only the records present in that run's
``results/`` are written, so partial runs stay partial and a set of runs jointly
covers the full input set.

Usage:
    tools/backfill_intermediate.py --case chemotion_eln RUN [RUN ...]
    tools/backfill_intermediate.py --case chemotion_eln --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pipeline  # noqa: E402
from cases import DEFAULT_CASE, available_cases, get_case  # noqa: E402


def resolve_run_dir(case, arg: str) -> Path | None:
    """Resolve a run id (folder under the case output) or a path to a run folder."""
    candidate = Path(arg)
    if candidate.is_dir():
        return candidate
    candidate = case.output_dir / arg
    return candidate if candidate.is_dir() else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", default=DEFAULT_CASE,
                        help=f"Case whose runs to backfill ({', '.join(available_cases())}).")
    parser.add_argument("runs", nargs="*", help="Run ids or folders to backfill.")
    parser.add_argument("--all", action="store_true",
                        help="Backfill every run_* folder of the case.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    case = get_case(args.case)

    if args.all:
        run_dirs = sorted(p for p in case.output_dir.glob("run_*") if p.is_dir())
    else:
        run_dirs = []
        for arg in args.runs:
            run_dir = resolve_run_dir(case, arg)
            if run_dir is None:
                print(f"Run not found: {arg!r}", file=sys.stderr)
                return 2
            run_dirs.append(run_dir)

    if not run_dirs:
        print("Nothing to do: pass run ids or --all.", file=sys.stderr)
        return 2

    for run_dir in run_dirs:
        count = pipeline.backfill_intermediate(case, run_dir)
        print(f"{run_dir.name}: wrote {count} intermediate file(s) to {run_dir / 'intermediate'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
