"""Tests for the `cli.py diff` command on top of mock-generated runs."""

from __future__ import annotations

import argparse

import cli


def _diff_args(**overrides) -> argparse.Namespace:
    base = dict(case="tiny", run_a=None, run_b=None, scope="all", output=None,
                full=False, context_lines=3, open=False)
    base.update(overrides)
    return argparse.Namespace(**base)


def test_diff_parser_registers_command():
    args = cli.build_parser().parse_args(
        ["diff", "--case", "chemotion_eln", "run_A", "run_B", "--scope", "inputs", "--full"])
    assert args.func is cli.cmd_diff
    assert (args.run_a, args.run_b, args.scope, args.full) == ("run_A", "run_B", "inputs", True)


def test_convert_parser_has_mock_flag():
    args = cli.build_parser().parse_args(["convert", "--mock", "--only", "R2"])
    assert args.mock is True and args.only == ["R2"]


def test_cmd_diff_writes_html_for_two_runs(run_mock_pipeline, monkeypatch, capsys):
    case, run = run_mock_pipeline
    run("run_A")
    case.records[0] = ("R1", {"journal_number": "R1", "value": 99})
    run("run_B")

    monkeypatch.setattr(cli.cases, "get_case", lambda name: case)
    assert cli.cmd_diff(_diff_args(run_a="run_A", run_b="run_B")) == 0

    output = case.output_dir / "run_B" / "diffs" / "rundiff_all_run_A_vs_run_B.html"
    assert output.is_file()
    page = output.read_text(encoding="utf-8")
    assert "results/R1.json" in page and "run_params.json" in page

    console = capsys.readouterr().out
    assert "changed" in console and "identical" in console


def test_cmd_diff_scope_inputs_defaults_to_latest_pair(run_mock_pipeline, monkeypatch, tmp_path):
    case, run = run_mock_pipeline
    run("run_A")
    (case.input_dir / "hints" / "h.md").write_text("hint v2", encoding="utf-8")
    run("run_B")

    monkeypatch.setattr(cli.cases, "get_case", lambda name: case)
    out = tmp_path / "inputs_diff.html"
    assert cli.cmd_diff(_diff_args(scope="inputs", output=out)) == 0

    page = out.read_text(encoding="utf-8")
    assert "hints/h.md" in page and "run_A" in page and "run_B" in page
