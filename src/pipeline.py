#!/usr/bin/env python3
"""Batch-convert one case's inputs into schema-validating JSON.

Produces a self-contained run folder under ``cases/<case>/output/``:

    run_<ts>/
    ├── inputs/        copy of the case inputs used (no secrets), incl.
    │                  run_params.json (CLI args + resolved endpoint config)
    ├── intermediate/  cleaned per-record JSON fed to the LLM (all records,
    │                  even when --only/--limit restricts the LLM calls)
    ├── results/       one JSON per record, generated this run
    ├── assembled/     results + gaps filled from the previous run
    ├── diffs/         vs previous run: diff_regenerated.json, diff_full.json,
    │                  diff_view.html (records) + rundiff_inputs.html,
    │                  rundiff_outputs.html (folder-level, incl. run params)
    ├── summary.json
    └── run_complete.json

Each run is recorded in ``cases/<case>/output/runs.json``. Applications are run
separately via ``cli.py applications``; this module only does conversion.

Use ``--dry-run`` to build and dump the full prompts without calling the model.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import folder_diff
import runs
from cases import DEFAULT_CASE, available_cases, get_case
from compare_outputs import compare_folders, to_jsonable
from convert import DEFAULT_ENDPOINT, build_prompt, load_config, mock_conversion, run_conversion
from diff_html import files_by_key, render_diff_page

_COMPLETE_MARKER = "run_complete.json"
REPO_ROOT = Path(__file__).resolve().parent.parent

# Usage counters accumulated across a run's conversions (see convert.run_conversion).
_TOKEN_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens",
               "prompt_chars", "completion_chars")


def _write_json(path: Path, data) -> None:
    """Write ``data`` as pretty UTF-8 JSON with a trailing newline."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_case_messages(case, preprocessed: dict, schema: dict, hints: str,
                        examples: list) -> list[dict[str, str]]:
    """Assemble the chat messages for one record, supplying the case's system
    prompt and rules. Wraps ``convert.build_prompt`` so callers don't repeat them."""
    prompt_record = case.prompt_record(preprocessed)
    prompt_examples = [
        {
            **example,
            "preprocessed_input": case.prompt_record(example["preprocessed_input"]),
        }
        for example in examples
    ]
    return build_prompt(
        prompt_record, schema, hints, prompt_examples, case.system_prompt, case.rules,
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """Register the conversion flags (shared by this module and cli.py)."""
    parser.add_argument("--case", default=DEFAULT_CASE,
                        help=f"Input case to convert ({', '.join(available_cases())}).")
    parser.add_argument("-o", "--output-dir", type=Path, default=None,
                        help="Run folder. Defaults to cases/<case>/output/run_<timestamp>.")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "config.json")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT,
                        help="Config endpoint / API key to use (default: openai).")
    parser.add_argument("--no-examples", action="store_true", help="Skip few-shot examples.")
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--limit", type=int, default=None,
                        help="Convert only the first N records (handy for testing).")
    parser.add_argument("--only", nargs="+", metavar="RECORD_ID", default=None,
                        help="Convert only these record ids (e.g. a single reaction). "
                             "Other records are carried over from the previous run when assembling.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Build and dump prompts without calling the model (no API key needed).")
    parser.add_argument("--mock", action="store_true",
                        help="Run the full pipeline (run folder, params, diffs, runs.json) with "
                             "deterministic placeholder results instead of calling the model "
                             "(no API key needed). The run folder is named run_<ts>_mock and is "
                             "never used as the baseline for later diffs.")


def write_diff_view(case_name: str, prev_run: Path, run_id: str,
                    results_dir: Path, diffs_dir: Path) -> dict[str, int]:
    """Write ``diffs/diff_view.html``: a side-by-side HTML diff of this run's
    freshly generated records against the same records in the previous assembled
    run. Records not regenerated this run are ignored (only ``results_dir`` keys
    are paired). Returns the change counts."""
    prev_files = files_by_key(prev_run / "assembled")
    new_files = files_by_key(results_dir)
    pairs = [(key, prev_files.get(key), new_files[key]) for key in sorted(new_files)]
    diff_page, diff_counts = render_diff_page(
        case_name, prev_run.name, run_id, pairs,
        a_meta=f"{prev_run.name}/assembled", b_meta=f"{run_id}/results",
    )
    diffs_dir.mkdir(exist_ok=True)
    (diffs_dir / "diff_view.html").write_text(diff_page, encoding="utf-8")
    return diff_counts


def find_previous_run(output_root: Path, current_dir: Path) -> Path | None:
    """Latest successful completed run to diff/assemble against.

    Mock runs and runs with failed records are never a baseline: neither
    represents a reliable prior conversion for assembly or comparison.
    """
    def is_successful(path: Path) -> bool:
        marker_path = path / _COMPLETE_MARKER
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return marker.get("status") == "complete" and marker.get("failures", 0) == 0

    runs_found = sorted(
        p for p in output_root.glob("run_*")
        if p.is_dir() and p != current_dir and not p.name.endswith("_mock")
        and is_successful(p)
    )
    return runs_found[-1] if runs_found else None


def _copy_into(src: Path, dest: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def build_run_params(args: argparse.Namespace, config: dict) -> dict:
    """Everything that parameterized this run, for ``inputs/run_params.json``.

    Captures the CLI args generically (``--endpoint``, ``--temperature``,
    ``--only``/``--limit`` record selection, …) so newly added flags are
    persisted automatically, plus the resolved endpoint block from the config
    (model, base_url, decoding params) — the part ``config.json`` alone cannot
    tell you, since it holds all endpoints. The API key is never included."""
    cli_args = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
        if key != "func" and not callable(value)
    }
    return {
        "command": sys.argv,
        "cli_args": cli_args,
        "endpoint": args.endpoint,
        "endpoint_config": {k: v for k, v in config.items() if k != "api_key"},
    }


def snapshot_inputs(case, config_path: Path, schema: dict, run_params: dict,
                    inputs_dir: Path) -> None:
    """Copy the case inputs used into the run so the folder is self-contained.

    secrets.json is never copied (it lives outside the case, in config/).
    """
    inputs_dir.mkdir(parents=True, exist_ok=True)
    _copy_into(case.input_dir, inputs_dir / "input")
    _copy_into(config_path, inputs_dir / "config.json")
    # The exact schema the model saw and validated against.
    _write_json(inputs_dir / "schema_used.json", schema)
    # The exact parameters of this run (endpoint, model, record selection, ...).
    _write_json(inputs_dir / "run_params.json", run_params)


def write_intermediate_records(records: list[tuple[str, dict]], intermediate_dir: Path) -> None:
    """Store each record's cleaned/preprocessed JSON — the exact per-record input
    the LLM sees — under ``intermediate/<record_id>.json``. The pipeline passes
    *all* of the case's records here (deriving them is cheap and deterministic),
    even when ``--only``/``--limit`` restricts which ones go to the LLM."""
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    for record_id, preprocessed in records:
        _write_json(intermediate_dir / f"{record_id}.json", preprocessed)


def backfill_intermediate(case, run_dir: Path) -> int:
    """Write the intermediate/ folder for an existing run, re-deriving the cleaned
    records for exactly the record ids present in the run's results/ (partial runs
    stay partial). Deterministic: assumes the cleaner and inputs are unchanged.
    Returns the number of records written."""
    results_dir = run_dir / "results"
    if not results_dir.is_dir():
        return 0
    wanted = {path.stem for path in results_dir.glob("*.json")}
    records = [(record_id, rec) for record_id, rec in case.iter_records() if record_id in wanted]
    write_intermediate_records(records, run_dir / "intermediate")
    return len(records)


def select_records(records: list[tuple[str, dict]], only: list[str] | None,
                   limit: int | None) -> list[tuple[str, dict]]:
    """Narrow the case's records to the ``--only`` ids and/or the first
    ``--limit`` of them. Raises ``SystemExit`` on an unknown ``--only`` id."""
    if only:
        # Record ids come from filenames, which macOS stores in NFD while a
        # typed --only argument is NFC: "geschützt" would never match.
        def key(rid: str) -> str:
            return unicodedata.normalize("NFC", rid)

        wanted = {key(rid) for rid in only}
        available = {key(rid) for rid, _ in records}
        missing = wanted - available
        if missing:
            raise SystemExit(f"--only: unknown record id(s): {', '.join(sorted(missing))}. "
                             f"Available: {', '.join(sorted(available))}.")
        records = [(rid, rec) for rid, rec in records if key(rid) in wanted]
    if limit is not None:
        records = records[:limit]
    return records


def write_dry_run_prompts(case, records, schema, hints, examples, out_dir: Path) -> int:
    """Build each record's prompt and dump it to ``out_dir/prompts`` without
    calling the model. Prints the count and an example prompt size."""
    prompts_dir = out_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    for record_id, preprocessed in records:
        messages = build_case_messages(case, preprocessed, schema, hints, examples)
        _write_json(prompts_dir / f"{record_id}.json", messages)
    example_chars = 0
    if records:
        sample = build_case_messages(case, records[0][1], schema, hints, examples)
        example_chars = sum(len(message["content"]) for message in sample)
    print(f"[dry-run] wrote {len(records)} prompt(s) to {prompts_dir}")
    print(f"[dry-run] example prompt size: ~{example_chars} chars, {len(examples)} few-shot example(s)")
    return 0


def _accumulate_tokens(totals: dict[str, int], usage: dict[str, int]) -> None:
    for key in _TOKEN_KEYS:
        totals[key] += usage.get(key, 0)


def convert_record(case, record_id: str, preprocessed: dict, schema: dict, hints: str,
                   examples: list, config: dict, temperature: float,
                   results_dir: Path, converter=run_conversion) -> tuple[dict, list[str]]:
    """Convert one record and write ``<results_dir>/<record_id>.json``.

    Returns ``(entry, validation_errors)`` where ``entry`` records the output
    path and token usage. Raises on any conversion/model error. ``converter``
    is ``run_conversion`` or, under ``--mock``, ``mock_conversion``."""
    messages = build_case_messages(case, preprocessed, schema, hints, examples)
    document, validation_errors, usage = converter(messages, schema, config, temperature)
    output_file = results_dir / f"{record_id}.json"
    _write_json(output_file, document)
    entry = {"record_id": record_id, "output_file": str(output_file), "usage": usage}
    return entry, validation_errors


def run_conversions(case, records, schema: dict, hints: str, examples: list,
                    config: dict, temperature: float, results_dir: Path,
                    converter=run_conversion) -> dict:
    """Convert every record to a JSON file, printing progress. Returns the
    results section of the summary (successes / validation_warnings / failures /
    tokens); records that raise are collected as failures rather than aborting."""
    results = {"successes": [], "validation_warnings": [], "failures": [],
               "tokens": {key: 0 for key in _TOKEN_KEYS}}
    for record_id, preprocessed in records:
        print(f"Converting {record_id} -> {record_id}.json")
        try:
            entry, validation_errors = convert_record(
                case, record_id, preprocessed, schema, hints, examples,
                config, temperature, results_dir, converter)
            _accumulate_tokens(results["tokens"], entry["usage"])
            if validation_errors:
                entry["errors"] = validation_errors
                results["validation_warnings"].append(entry)
                print(f"  saved with {len(validation_errors)} validation warning(s)")
            else:
                results["successes"].append(entry)
                print("  validation OK")
        except Exception as exc:
            results["failures"].append({"record_id": record_id, "error": str(exc)})
            print(f"  FAILED: {exc}", file=sys.stderr)
    return results


def assemble_outputs(results_dir: Path, prev_run: Path | None, assembled_dir: Path) -> None:
    """Populate ``assembled_dir`` with this run's results, then fill any gaps
    from the previous run's assembled set so it holds the full record set."""
    assembled_dir.mkdir(exist_ok=True)
    for json_file in sorted(results_dir.glob("*.json")):
        shutil.copy2(json_file, assembled_dir / json_file.name)
    if prev_run and (prev_run / "assembled").is_dir():
        for json_file in sorted((prev_run / "assembled").glob("*.json")):
            dest = assembled_dir / json_file.name
            if not dest.exists():
                shutil.copy2(json_file, dest)


def write_json_diffs(prev_assembled: Path, results_dir: Path,
                     assembled_dir: Path, diffs_dir: Path) -> tuple[int, int]:
    """Write ``diff_regenerated.json`` (this run's regenerated records vs the
    previous run) and ``diff_full.json`` (the whole assembled set vs previous).
    Returns the number of differing files in each."""
    diffs_dir.mkdir(exist_ok=True)
    regen_diff = compare_folders(prev_assembled, results_dir, name_filter=None)
    _write_json(diffs_dir / "diff_regenerated.json", to_jsonable(regen_diff))
    full_diff = compare_folders(prev_assembled, assembled_dir, name_filter=None)
    _write_json(diffs_dir / "diff_full.json", to_jsonable(full_diff))
    return len(regen_diff), len(full_diff)


def write_run_diffs(case_name: str, prev_run: Path, run_id: str,
                    results_dir: Path, assembled_dir: Path, diffs_dir: Path) -> None:
    """Write both the machine-readable JSON diffs and the HTML diff view
    comparing this run against the previous run."""
    n_regen, n_full = write_json_diffs(prev_run / "assembled", results_dir, assembled_dir, diffs_dir)
    print(f"Diffs: diff_regenerated.json ({n_regen} files), diff_full.json ({n_full} files)")
    counts = write_diff_view(case_name, prev_run, run_id, results_dir, diffs_dir)
    print(f"Diff view: diff_view.html ({counts['changed']} changed, "
          f"{counts['added']} new, {counts['identical']} identical)")


def write_folder_diffs(case_name: str, prev_run: Path, run_dir: Path, diffs_dir: Path) -> None:
    """Auto-write git-style folder diffs of this run vs the previous run:
    ``diffs/rundiff_inputs.html`` (config, run params, hints, examples, raw
    data) and ``diffs/rundiff_outputs.html`` (results, intermediate, summary…).

    Mirrors the record-level auto-diff: in the outputs diff, files present only
    in the previous run (records not regenerated on a ``--only``/``--limit``
    run) are skipped. Use ``cli.py diff`` to compare whole runs instead."""
    diffs_dir.mkdir(exist_ok=True)
    for scope in ("inputs", "outputs"):
        entries, a_root, b_root = folder_diff.diff_run_scope(prev_run, run_dir, scope)
        if scope == "outputs":
            entries = [e for e in entries if e.status != "removed"]
        page, counts = folder_diff.render_folder_diff_page(
            f"{case_name} ({scope})", prev_run.name, run_dir.name, entries,
            a_meta=str(a_root), b_meta=str(b_root),
        )
        (diffs_dir / f"rundiff_{scope}.html").write_text(page, encoding="utf-8")
        print(f"Run diff ({scope}): rundiff_{scope}.html ({counts['changed']} changed, "
              f"{counts['added']} new, {counts['identical']} identical)")


def new_run_summary(run_id: str, case_name: str, output_dir: Path,
                    results_dir: Path, prev_run: Path | None, total: int) -> dict:
    """The run's metadata header, to which the conversion results are merged."""
    return {
        "run_id": run_id,
        "case": case_name,
        "output_dir": str(output_dir),
        "results_dir": str(results_dir),
        "previous_run": str(prev_run) if prev_run else None,
        "total": total,
    }


def write_completion_marker(output_dir: Path, summary: dict, finished_at: str) -> None:
    """Write ``run_complete.json`` marking the run as finished (used by
    ``find_previous_run`` to skip incomplete runs)."""
    _write_json(output_dir / _COMPLETE_MARKER, {
        "status": "complete", "finished_at": finished_at, "total": summary["total"],
        "successes": len(summary["successes"]),
        "validation_warnings": len(summary["validation_warnings"]),
        "failures": len(summary["failures"]),
    })


def append_run_record(runs_file: Path, summary: dict, args: argparse.Namespace,
                      model: str | None, run_params: dict,
                      prev_run: Path | None, finished_at: str) -> None:
    """Record this run in the case's runs.json (see runs.append_run)."""
    runs.append_run({
        "run_id": summary["run_id"],
        "case": summary["case"],
        "timestamp": finished_at,
        "output_dir": summary["output_dir"],
        "config": str(args.config),
        "endpoint": args.endpoint,
        "model": model,
        "params": run_params,
        "previous_run": prev_run.name if prev_run else None,
        "total": summary["total"],
        "successes": len(summary["successes"]),
        "validation_warnings": len(summary["validation_warnings"]),
        "failures": len(summary["failures"]),
        "tokens": summary["tokens"],
        "applications_run": None,
    }, runs_file=runs_file)


def run(args: argparse.Namespace) -> int:
    case = get_case(args.case)
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M")

    all_records = list(case.iter_records())
    records = select_records(all_records, args.only, args.limit)
    if not records:
        print(f"No records selected for case {case.name!r}. "
              f"Check the raw data under {case.input_dir} and the selection options.",
              file=sys.stderr)
        return 2
    schema, hints = case.schema(), case.hints()
    examples = [] if args.no_examples else case.load_examples()
    print(f"Case: {case.name} | records: {len(records)}/{len(all_records)} | examples: {len(examples)}")

    if args.dry_run:
        out_dir = args.output_dir or (case.output_dir / f"_dryrun_{timestamp}")
        return write_dry_run_prompts(case, records, schema, hints, examples, out_dir)

    if args.mock:
        # Full pipeline, no model: placeholder results, clearly-marked run folder.
        args.endpoint = "mock"
        config = {"endpoint": "mock", "model": "mock", "base_url": None}
        converter = mock_conversion
    else:
        config = load_config(args.config, args.endpoint)
        converter = run_conversion
    run_suffix = "_mock" if args.mock else ""
    output_dir = args.output_dir or (case.output_dir / f"run_{timestamp}{run_suffix}")
    results_dir = output_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    run_id = output_dir.name

    prev_run = find_previous_run(case.output_dir, output_dir)
    print(f"Previous run: {prev_run or 'none'}")
    run_params = build_run_params(args, config)
    snapshot_inputs(case, args.config, schema, run_params, output_dir / "inputs")
    # Intermediate records are written for the whole record set, not just the
    # subset sent to the LLM: deriving them is cheap and keeps every run's
    # intermediate/ complete and comparable.
    write_intermediate_records(all_records, output_dir / "intermediate")

    results = run_conversions(case, records, schema, hints, examples,
                              config, args.temperature, results_dir, converter)
    summary = {**new_run_summary(run_id, case.name, output_dir, results_dir, prev_run, len(records)),
               **results}

    assembled_dir = output_dir / "assembled"
    assemble_outputs(results_dir, prev_run, assembled_dir)
    summary["assembled_dir"] = str(assembled_dir)
    _write_json(output_dir / "summary.json", summary)

    if prev_run and (prev_run / "assembled").is_dir():
        write_run_diffs(case.name, prev_run, run_id, results_dir, assembled_dir, output_dir / "diffs")

    finished_at = datetime.now().isoformat(timespec="seconds")
    write_completion_marker(output_dir, summary, finished_at)
    if prev_run:
        # Folder-level auto-diff (inputs + outputs) vs the previous run; written
        # after the completion marker so summary/run_complete are included.
        write_folder_diffs(case.name, prev_run, output_dir, output_dir / "diffs")
    append_run_record(case.output_dir / "runs.json", summary, args,
                      config.get("model"), run_params, prev_run, finished_at)

    print(f"\nSummary: {output_dir / 'summary.json'}")
    print(f"Assembled: {assembled_dir}")
    print("Done: "
          f"{len(summary['successes'])} valid, "
          f"{len(summary['validation_warnings'])} saved with warnings, "
          f"{len(summary['failures'])} failed.")
    return 1 if summary["failures"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert one case's inputs to target JSON.")
    add_arguments(parser)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
