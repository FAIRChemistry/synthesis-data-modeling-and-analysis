"""Exercise the shipped application through the CLI and its real subprocess."""

import argparse
import json

import cli


def test_default_applications_export_xdl_for_both_cases(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    assembled = run_dir / "assembled"
    assembled.mkdir(parents=True)
    (assembled / "record.json").write_text(json.dumps({
        "journal_number": "R1", "starting_materials": [], "products": [],
        "procedure": {"Reaction": {"Step": [{"$xml_type": "Stir"}]}},
    }))
    monkeypatch.setattr(cli, "resolve_run_dir", lambda case, run: run_dir)
    monkeypatch.setattr(cli.runs, "update_run", lambda *args, **kwargs: None)

    for case_name in cli.cases.available_cases():
        args = argparse.Namespace(case=case_name, run=None, only=None)
        assert cli.cmd_applications(args) == 0
        xml = run_dir / "applications" / "xdl_export" / "R1.xdl"
        assert "<Stir" in xml.read_text()
