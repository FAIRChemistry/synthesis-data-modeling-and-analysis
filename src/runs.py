#!/usr/bin/env python3
"""Single source of truth for tracking conversion runs.

Every conversion writes one record to a runs file (per case:
``cases/<case>/output/runs.json``, passed in as ``runs_file``). The
applications command updates the matching record in place once it has run. This
module is the only place that reads or writes that file so the format stays
consistent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUTPUT_ROOT = Path("output")
RUNS_FILE = OUTPUT_ROOT / "runs.json"


def load_runs(runs_file: Path = RUNS_FILE) -> list[dict[str, Any]]:
    if not runs_file.exists():
        return []
    data = json.loads(runs_file.read_text(encoding="utf-8"))
    return data.get("runs", [])


def _save(runs: list[dict[str, Any]], runs_file: Path = RUNS_FILE) -> None:
    runs_file.parent.mkdir(parents=True, exist_ok=True)
    runs_file.write_text(
        json.dumps({"runs": runs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_run(entry: dict[str, Any], runs_file: Path = RUNS_FILE) -> None:
    """Add a new run record (replacing any existing record with the same id)."""
    runs = [r for r in load_runs(runs_file) if r.get("run_id") != entry.get("run_id")]
    runs.append(entry)
    _save(runs, runs_file)


def update_run(run_id: str, runs_file: Path = RUNS_FILE, **fields: Any) -> bool:
    """Merge ``fields`` into the record for ``run_id``. Returns True if found."""
    runs = load_runs(runs_file)
    for record in runs:
        if record.get("run_id") == run_id:
            record.update(fields)
            _save(runs, runs_file)
            return True
    return False


def get_run(run_id: str, runs_file: Path = RUNS_FILE) -> dict[str, Any] | None:
    for record in load_runs(runs_file):
        if record.get("run_id") == run_id:
            return record
    return None


def latest_run(runs_file: Path = RUNS_FILE) -> dict[str, Any] | None:
    runs = load_runs(runs_file)
    return runs[-1] if runs else None


# --------------------------------------------------------------------------- #
# Run-folder resolution (shared by cli.py diff and tools/diff_viewer.py)      #
# --------------------------------------------------------------------------- #

def resolve_run_dir(case, arg: str | None) -> Path | None:
    """Resolve a run id (folder under the case output) or a path to a run folder."""
    if not arg:
        return None
    candidate = Path(arg)
    if candidate.is_dir():
        return candidate
    candidate = case.output_dir / arg
    return candidate if candidate.is_dir() else None


def default_pair(case, run_a: str | None, run_b: str | None) -> tuple[Path, Path]:
    """Fill in the missing run(s): default b to the latest run and a to its
    predecessor (``previous_run`` from runs.json, else the run recorded before it)."""
    runs_file = case.output_dir / "runs.json"
    records = load_runs(runs_file=runs_file)

    b_dir = resolve_run_dir(case, run_b)
    if b_dir is None:
        if not records:
            raise SystemExit(f"No runs found for case {case.name!r}. Run a conversion first.")
        b_dir = resolve_run_dir(case, records[-1]["run_id"]) or Path(records[-1]["output_dir"])

    a_dir = resolve_run_dir(case, run_a)
    if a_dir is None:
        rec = get_run(b_dir.name, runs_file=runs_file)
        prev_id = rec.get("previous_run") if rec else None
        if not prev_id:
            ids = [r["run_id"] for r in records]
            if b_dir.name in ids and ids.index(b_dir.name) > 0:
                prev_id = ids[ids.index(b_dir.name) - 1]
        if not prev_id:
            raise SystemExit(
                f"Could not determine a run to compare against {b_dir.name!r}. "
                "Pass two runs explicitly: <run_a> <run_b>."
            )
        a_dir = resolve_run_dir(case, prev_id)
        if a_dir is None:
            raise SystemExit(f"Previous run {prev_id!r} not found on disk.")
    return a_dir, b_dir
