#!/usr/bin/env python3
"""DiffViewer — a side-by-side, git-style HTML diff of two conversion runs.

Given two runs of *any* case, render every record's JSON output next to each
other in a single self-contained HTML page: additions in green, deletions in
red, changes highlighted — just like a Git diff.

Rendering is done by ``src/diff_html.py`` (which wraps the standard library's
``difflib.HtmlDiff``); this script only resolves the two runs and pairs their
record folders. The same renderer is used by the conversion pipeline to write a
diff view automatically after every run.

Usage (run ids are folder names under ``cases/<case>/output/`` or full paths):

    tools/diff_viewer.py --case chemotion_eln                  # previous vs latest
    tools/diff_viewer.py --case chemotion_eln run_B            # run_B's previous vs run_B
    tools/diff_viewer.py --case chemotion_eln run_A run_B      # explicit pair
    tools/diff_viewer.py run_A run_B -o diff.html --open  # write + open in browser
    tools/diff_viewer.py run_A run_B --full                    # whole files, not just hunks

By default the ``assembled/`` folder of each run is compared (falling back to
``results/``); override with ``--subdir``.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import runs  # noqa: E402
from cases import DEFAULT_CASE, available_cases, get_case  # noqa: E402
from diff_html import files_by_key, render_diff_page  # noqa: E402

# Compared in preference order when --subdir is left at its default.
_DEFAULT_SUBDIRS = ("assembled", "results")


def pick_subdir(run_dir: Path, subdir: str | None) -> Path:
    """Locate the folder of per-record JSONs to compare within a run."""
    if subdir:
        chosen = run_dir / subdir
        if not chosen.is_dir():
            raise SystemExit(f"{chosen} is not a directory.")
        return chosen
    for name in _DEFAULT_SUBDIRS:
        if (run_dir / name).is_dir():
            return run_dir / name
    raise SystemExit(f"No {' or '.join(_DEFAULT_SUBDIRS)} folder in {run_dir}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", default=DEFAULT_CASE,
                        help=f"Case whose runs to diff ({', '.join(available_cases())}).")
    parser.add_argument("run_a", nargs="?", default=None,
                        help="Baseline run id or folder (default: run_b's predecessor).")
    parser.add_argument("run_b", nargs="?", default=None,
                        help="New run id or folder (default: the latest run).")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="HTML output path (default: <run_b>/diffs/diff_<run_a>_vs_<run_b>.html).")
    parser.add_argument("--subdir", default=None,
                        help=f"Which per-record folder to compare (default: first of "
                             f"{', '.join(_DEFAULT_SUBDIRS)}).")
    parser.add_argument("--full", action="store_true",
                        help="Show whole files side by side (default: only changed hunks, like git diff).")
    parser.add_argument("--context-lines", type=int, default=3,
                        help="Unchanged context lines around each hunk (default: 3).")
    parser.add_argument("--open", action="store_true", help="Open the page in a browser when done.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    case = get_case(args.case)

    a_run, b_run = runs.default_pair(case, args.run_a, args.run_b)
    a_sub = pick_subdir(a_run, args.subdir)
    b_sub = pick_subdir(b_run, args.subdir)

    # CLI compares the union of both folders (the whole runs).
    a_files, b_files = files_by_key(a_sub), files_by_key(b_sub)
    pairs = [(k, a_files.get(k), b_files.get(k)) for k in sorted(set(a_files) | set(b_files))]

    page, counts = render_diff_page(
        case.name, a_run.name, b_run.name, pairs,
        a_meta=str(a_sub), b_meta=str(b_sub),
        full=args.full, context_lines=args.context_lines,
    )

    output = args.output or (b_run / "diffs" / f"diff_{a_run.name}_vs_{b_run.name}.html")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")

    print(f"Compared {a_run.name} → {b_run.name}")
    print(f"  {counts['changed']} changed, {counts['added']} only in B, "
          f"{counts['removed']} only in A, {counts['identical']} identical")
    print(f"Wrote {output}")
    if args.open:
        webbrowser.open(output.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
