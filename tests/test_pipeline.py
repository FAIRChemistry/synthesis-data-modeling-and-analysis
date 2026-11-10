"""Tests for the conversion pipeline: record selection, run-parameter
persistence, all-records intermediate, mock mode, and the automatic run diffs.
Everything runs offline via --mock (no API key)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import pipeline
from conftest import default_records


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# select_records
# --------------------------------------------------------------------------- #

def test_select_records_only_and_limit():
    records = default_records()
    assert [r[0] for r in pipeline.select_records(records, None, None)] == ["R1", "R2", "R3"]
    assert [r[0] for r in pipeline.select_records(records, ["R2"], None)] == ["R2"]
    assert [r[0] for r in pipeline.select_records(records, None, 2)] == ["R1", "R2"]
    assert [r[0] for r in pipeline.select_records(records, ["R1", "R3"], 1)] == ["R1"]


def test_select_records_unknown_id_raises():
    with pytest.raises(SystemExit, match="unknown record id"):
        pipeline.select_records(default_records(), ["nope"], None)


@pytest.mark.parametrize("records,limit", [([], None), (default_records(), 0)])
def test_empty_selection_does_not_create_a_successful_run(
        tiny_case, convert_args, monkeypatch, capsys, records, limit):
    case = tiny_case(records=records)
    monkeypatch.setattr(pipeline, "get_case", lambda name: case)

    assert pipeline.run(convert_args(limit=limit)) == 2
    assert "No records selected" in capsys.readouterr().err
    assert not case.output_dir.exists()


def test_build_case_messages_uses_case_specific_prompt_view():
    class CompactCase:
        system_prompt = "system"
        rules = ["rule"]

        @staticmethod
        def prompt_record(record):
            return {"kept": record["kept"]}

    messages = pipeline.build_case_messages(
        CompactCase(),
        {"kept": "record", "audit_only": "large"},
        {"type": "object"},
        "hints",
        [{
            "filename": "example",
            "preprocessed_input": {"kept": "example", "audit_only": "large"},
            "target_json": {"ok": True},
        }],
    )

    user = json.loads(messages[-1]["content"])
    assert user["preprocessed_input"] == {"kept": "record"}
    pair = user["examples"][0]["pairs"][0]
    assert pair["preprocessed_input"] == {"kept": "example"}
    assert pair["target_json"] == {"ok": True}


# --------------------------------------------------------------------------- #
# run parameter persistence
# --------------------------------------------------------------------------- #

def test_build_run_params_captures_cli_args_without_secrets(convert_args):
    args = convert_args(endpoint="blablador", temperature=0.7, only=["R2"], limit=5)
    config = {"endpoint": "blablador", "model": "alias-fast",
              "base_url": "https://example", "api_key": "SECRET"}

    params = pipeline.build_run_params(args, config)

    cli = params["cli_args"]
    assert cli["endpoint"] == "blablador" and cli["temperature"] == 0.7
    assert cli["only"] == ["R2"] and cli["limit"] == 5
    assert isinstance(cli["config"], str)  # Paths are serialized
    assert params["endpoint_config"]["model"] == "alias-fast"
    assert "SECRET" not in json.dumps(params)
    assert "api_key" not in params["endpoint_config"]


def test_snapshot_inputs_is_self_contained(tiny_case, convert_args, tmp_path):
    case = tiny_case()
    args = convert_args()
    params = pipeline.build_run_params(args, {"model": "m", "api_key": "SECRET"})
    inputs_dir = tmp_path / "run" / "inputs"

    pipeline.snapshot_inputs(case, args.config, case.schema(), params, inputs_dir)

    assert (inputs_dir / "input" / "hints" / "h.md").read_text() == "hint v1"
    assert (inputs_dir / "config.json").is_file()
    assert (inputs_dir / "schema_used.json").is_file()
    assert _read_json(inputs_dir / "run_params.json")["cli_args"]["case"] == "tiny"


# --------------------------------------------------------------------------- #
# previous-run discovery
# --------------------------------------------------------------------------- #

def test_find_previous_run_skips_incomplete_mock_and_failed_runs(tmp_path):
    complete = {"status": "complete"}
    failed = {"status": "complete", "failures": 1}
    for name, marker in (("run_1", complete), ("run_2_mock", complete),
                         ("run_3", None), ("run_4", failed)):
        (tmp_path / name).mkdir()
        if marker:
            (tmp_path / name / "run_complete.json").write_text(json.dumps(marker))
    current = tmp_path / "run_5"
    current.mkdir()

    assert pipeline.find_previous_run(tmp_path, current) == tmp_path / "run_1"


# --------------------------------------------------------------------------- #
# mock mode end-to-end (full run, then a partial --only re-run)
# --------------------------------------------------------------------------- #

def test_mock_run_produces_complete_tracked_run(run_mock_pipeline):
    case, run = run_mock_pipeline
    run_a = run("run_A")

    assert len(list((run_a / "results").glob("*.json"))) == 3
    assert len(list((run_a / "intermediate").glob("*.json"))) == 3
    assert len(list((run_a / "assembled").glob("*.json"))) == 3
    assert (run_a / "run_complete.json").is_file()
    assert (run_a / "inputs" / "run_params.json").is_file()

    record = _read_json(case.output_dir / "runs.json")["runs"][-1]
    assert record["run_id"] == "run_A"
    assert record["endpoint"] == "mock" and record["model"] == "mock"
    assert record["params"]["cli_args"]["mock"] is True


def test_partial_rerun_keeps_intermediate_complete_and_diffs_inputs(run_mock_pipeline):
    case, run = run_mock_pipeline
    run("run_A")

    # Second run: R2's source record changed, hints changed, only R2 re-converted.
    case.records[1] = ("R2", {"journal_number": "R2", "value": 2})
    (case.input_dir / "hints" / "h.md").write_text("hint v2", encoding="utf-8")
    run_b = run("run_B", only=["R2"], temperature=0.5)

    # LLM ran only for R2, but intermediate covers all records and the
    # assembled set is complete (gaps filled from run_A).
    assert [p.stem for p in sorted((run_b / "results").glob("*.json"))] == ["R2"]
    assert len(list((run_b / "intermediate").glob("*.json"))) == 3
    assert len(list((run_b / "assembled").glob("*.json"))) == 3

    # The run's parameters (incl. which records were re-run) are persisted.
    params = _read_json(run_b / "inputs" / "run_params.json")
    assert params["cli_args"]["only"] == ["R2"]
    assert params["cli_args"]["temperature"] == 0.5
    record = _read_json(case.output_dir / "runs.json")["runs"][-1]
    assert record["params"]["cli_args"]["only"] == ["R2"]

    # Automatic diffs vs run_A: record-level view + both folder-level views.
    diffs = run_b / "diffs"
    for name in ("diff_view.html", "diff_regenerated.json", "diff_full.json",
                 "rundiff_inputs.html", "rundiff_outputs.html"):
        assert (diffs / name).is_file(), name

    inputs_page = (diffs / "rundiff_inputs.html").read_text(encoding="utf-8")
    assert "hints/h.md" in inputs_page and "run_params.json" in inputs_page

    # Outputs auto-diff compares only what this run regenerated: R2 gets a
    # file section, the not-regenerated R1/R3 results are not reported as removed.
    outputs_page = (diffs / "rundiff_outputs.html").read_text(encoding="utf-8")
    assert 'id="f-results-R2-json"' in outputs_page
    assert 'id="f-results-R1-json"' not in outputs_page
    assert ">0 only in A</span>" in outputs_page


def test_mock_default_run_folder_is_marked(tiny_case, convert_args, monkeypatch):
    case = tiny_case()
    monkeypatch.setattr(pipeline, "get_case", lambda name: case)
    assert pipeline.run(convert_args()) == 0  # default output dir

    (run_dir,) = [p for p in case.output_dir.glob("run_*") if p.is_dir()]
    assert run_dir.name.endswith("_mock")
    # A mock run is never picked as the baseline for the next run.
    assert pipeline.find_previous_run(case.output_dir, case.output_dir / "x") is None
