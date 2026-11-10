#!/usr/bin/env python3
"""Front-facing CLI for the lab-journal conversion project.

Run from the repository root:

    python cli.py convert                          # convert the default (excel) case
    python cli.py convert --case chemotion_eln     # convert the Chemotion ELN case
    python cli.py convert --case chemotion_eln --dry-run   # build prompts, no API call
    python cli.py convert --case chemotion_eln --mock      # full pipeline, placeholder results
    python cli.py applications                      # run apps on the latest run
    python cli.py applications --case chemotion_eln
    python cli.py list                              # show tracked runs (all cases)
    python cli.py diff                              # folder diff: previous vs latest run
    python cli.py diff --scope inputs run_A run_B   # what inputs/params differed?

Each case lives under ``cases/<case>/`` with its own ``input/`` and ``output/``.
`convert` produces a self-contained run folder; `applications` (alias `apps`)
runs applications on a run's records. The two are intentionally separate commands.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
APPLICATIONS_DIR = ROOT / "applications"

sys.path.insert(0, str(SRC))

import cases  # noqa: E402  (after sys.path tweak)
import folder_diff  # noqa: E402
import pipeline  # noqa: E402
import runs  # noqa: E402

# Registered applications; paper analyses also live under generated_analyses/.
APPLICATIONS = {
    "xdl_export": "xdl_export.py",
}


def cmd_convert(args: argparse.Namespace) -> int:
    return pipeline.run(args)


# --------------------------------------------------------------------------- #
# applications
# --------------------------------------------------------------------------- #
def resolve_run_dir(case, run_arg: str | None) -> Path | None:
    """Resolve a run argument to its output folder (within the case)."""
    if run_arg:
        return runs.resolve_run_dir(case, run_arg)
    latest = runs.latest_run(runs_file=case.output_dir / "runs.json")
    if not latest:
        return None
    # Resolve by run_id under the case output dir (robust to moved folders),
    # falling back to the stored path.
    run_id = latest.get("run_id")
    if run_id and (case.output_dir / run_id).is_dir():
        return case.output_dir / run_id
    stored = latest.get("output_dir")
    return Path(stored) if stored and Path(stored).is_dir() else None


def cmd_applications(args: argparse.Namespace) -> int:
    case = cases.get_case(args.case)
    run_dir = resolve_run_dir(case, args.run)
    if run_dir is None or not run_dir.is_dir():
        print(f"Could not resolve a run folder for case {args.case!r} from {args.run!r}. "
              "Run `python cli.py list` to see available runs.", file=sys.stderr)
        return 2

    input_dir = run_dir / "assembled"
    if not input_dir.is_dir():
        input_dir = run_dir / "results"
    if not input_dir.is_dir():
        print(f"No results found in {run_dir}.", file=sys.stderr)
        return 2

    selected = args.only or list(APPLICATIONS)
    unknown = [name for name in selected if name not in APPLICATIONS]
    if unknown:
        print(f"Unknown application(s): {', '.join(unknown)}. "
              f"Available: {', '.join(APPLICATIONS)}", file=sys.stderr)
        return 2

    print(f"Case: {args.case}\nRun: {run_dir}\nInput: {input_dir}")
    failures = 0
    for name in selected:
        out_dir = run_dir / "applications" / name
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n{name}")
        result = subprocess.run(
            [sys.executable, APPLICATIONS[name],
             "--input", str(input_dir.resolve()),
             "--output", str(out_dir.resolve())],
            cwd=APPLICATIONS_DIR,
        )
        if result.returncode != 0:
            failures += 1
            print(f"  {name} exited with code {result.returncode}", file=sys.stderr)

    runs.update_run(
        run_dir.name,
        runs_file=case.output_dir / "runs.json",
        applications_run={"names": selected, "timestamp": datetime.now().isoformat(timespec="seconds")},
    )
    print(f"\nApplications written under {run_dir / 'applications'}")
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# diff
# --------------------------------------------------------------------------- #
def cmd_diff(args: argparse.Namespace) -> int:
    case = cases.get_case(args.case)
    a_run, b_run = runs.default_pair(case, args.run_a, args.run_b)
    entries, a_root, b_root = folder_diff.diff_run_scope(a_run, b_run, args.scope)
    page, _ = folder_diff.render_folder_diff_page(
        f"{case.name} ({args.scope})", a_run.name, b_run.name, entries,
        a_meta=str(a_root), b_meta=str(b_root),
        full=args.full, context_lines=args.context_lines,
    )

    output = args.output or (b_run / "diffs" / f"rundiff_{args.scope}_{a_run.name}_vs_{b_run.name}.html")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")

    print(f"Compared {a_run.name} -> {b_run.name} (scope: {args.scope})")
    folder_diff.print_summary(entries)
    print(f"Wrote {output}")
    if args.open:
        webbrowser.open(output.resolve().as_uri())
    return 0


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #
def cmd_list(args: argparse.Namespace) -> int:
    case_names = [args.case] if args.case else cases.available_cases()
    any_runs = False
    for case_name in case_names:
        case = cases.get_case(case_name)
        records = runs.load_runs(runs_file=case.output_dir / "runs.json")
        if not records:
            continue
        any_runs = True
        print(f"\n[{case_name}]")
        for r in records:
            apps = r.get("applications_run")
            apps_str = ",".join(apps["names"]) if apps else "-"
            print(
                f"  {r.get('run_id'):28}  {r.get('timestamp', ''):20}  "
                f"{r.get('endpoint')}:{r.get('model')}  "
                f"ok={r.get('successes')}/{r.get('total')}  "
                f"warn={r.get('validation_warnings')}  fail={r.get('failures')}  "
                f"apps={apps_str}"
            )
    if not any_runs:
        print("No runs recorded yet. Run `python cli.py convert` first.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_convert = sub.add_parser("convert", help="Convert a case's inputs into a new run folder.")
    pipeline.add_arguments(p_convert)
    p_convert.set_defaults(func=cmd_convert)

    p_apps = sub.add_parser("applications", aliases=["apps"],
                            help="Run applications on a run's output.")
    p_apps.add_argument("--case", default=cases.DEFAULT_CASE,
                        help=f"Case whose run to use ({', '.join(cases.available_cases())}).")
    p_apps.add_argument("run", nargs="?", default=None,
                        help="Run id or folder (default: most recent run of the case).")
    p_apps.add_argument("--only", nargs="+", metavar="NAME",
                        help=f"Subset of applications to run ({', '.join(APPLICATIONS)}).")
    p_apps.set_defaults(func=cmd_applications)

    p_diff = sub.add_parser(
        "diff",
        help="Git-style folder diff between two runs (inputs, outputs, or both) as HTML + console summary.")
    p_diff.add_argument("--case", default=cases.DEFAULT_CASE,
                        help=f"Case whose runs to diff ({', '.join(cases.available_cases())}).")
    p_diff.add_argument("run_a", nargs="?", default=None,
                        help="Baseline run id or folder (default: run_b's predecessor).")
    p_diff.add_argument("run_b", nargs="?", default=None,
                        help="New run id or folder (default: the latest run).")
    p_diff.add_argument("--scope", choices=sorted(folder_diff.RUN_DIFF_SCOPES), default="all",
                        help="inputs: only inputs/ (config, params, hints, examples, raw data); "
                             "outputs: everything but inputs/; all: the whole run folder (default).")
    p_diff.add_argument("-o", "--output", type=Path, default=None,
                        help="HTML output path (default: <run_b>/diffs/rundiff_<scope>_<a>_vs_<b>.html).")
    p_diff.add_argument("--full", action="store_true",
                        help="Show whole files side by side (default: only changed hunks, like git diff).")
    p_diff.add_argument("--context-lines", type=int, default=3,
                        help="Unchanged context lines around each hunk (default: 3).")
    p_diff.add_argument("--open", action="store_true", help="Open the page in a browser when done.")
    p_diff.set_defaults(func=cmd_diff)

    p_list = sub.add_parser("list", help="List tracked runs.")
    p_list.add_argument("--case", default=None,
                        help="Restrict to one case (default: all cases).")
    p_list.set_defaults(func=cmd_list)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
