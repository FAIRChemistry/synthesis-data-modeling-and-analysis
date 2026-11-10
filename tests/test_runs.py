"""Unit tests for run tracking and run-folder resolution (src/runs.py)."""

from __future__ import annotations

import pytest

import runs


def test_append_update_get_latest_roundtrip(tmp_path):
    runs_file = tmp_path / "runs.json"
    runs.append_run({"run_id": "run_1", "model": "m"}, runs_file=runs_file)
    runs.append_run({"run_id": "run_2", "model": "m"}, runs_file=runs_file)

    assert [r["run_id"] for r in runs.load_runs(runs_file)] == ["run_1", "run_2"]
    assert runs.latest_run(runs_file)["run_id"] == "run_2"

    assert runs.update_run("run_1", runs_file=runs_file, note="x")
    assert runs.get_run("run_1", runs_file=runs_file)["note"] == "x"
    assert not runs.update_run("missing", runs_file=runs_file, note="x")

    # Re-appending the same id replaces the record instead of duplicating it.
    runs.append_run({"run_id": "run_2", "model": "m2"}, runs_file=runs_file)
    assert len(runs.load_runs(runs_file)) == 2
    assert runs.get_run("run_2", runs_file=runs_file)["model"] == "m2"


class _StubCase:
    name = "stub"

    def __init__(self, output_dir):
        self.output_dir = output_dir


@pytest.fixture
def case_with_runs(tmp_path):
    case = _StubCase(tmp_path / "output")
    for run_id, prev in (("run_1", None), ("run_2", "run_1"), ("run_3", "run_2")):
        (case.output_dir / run_id).mkdir(parents=True)
        runs.append_run({"run_id": run_id, "previous_run": prev,
                         "output_dir": str(case.output_dir / run_id)},
                        runs_file=case.output_dir / "runs.json")
    return case


def test_resolve_run_dir(case_with_runs, tmp_path):
    case = case_with_runs
    assert runs.resolve_run_dir(case, "run_2") == case.output_dir / "run_2"
    assert runs.resolve_run_dir(case, str(case.output_dir / "run_1")) == case.output_dir / "run_1"
    assert runs.resolve_run_dir(case, "nope") is None
    assert runs.resolve_run_dir(case, None) is None


def test_default_pair_defaults_to_latest_and_predecessor(case_with_runs):
    case = case_with_runs
    a, b = runs.default_pair(case, None, None)
    assert (a.name, b.name) == ("run_2", "run_3")

    a, b = runs.default_pair(case, None, "run_2")
    assert (a.name, b.name) == ("run_1", "run_2")

    a, b = runs.default_pair(case, "run_1", "run_3")
    assert (a.name, b.name) == ("run_1", "run_3")


def test_default_pair_without_runs_raises(tmp_path):
    with pytest.raises(SystemExit):
        runs.default_pair(_StubCase(tmp_path / "empty"), None, None)
