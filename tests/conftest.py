"""Shared fixtures: a tiny synthetic case that runs the real pipeline in mock
mode inside a tmp directory — no API key, no real case data touched."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for entry in (str(ROOT), str(ROOT / "src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import cases  # noqa: E402

# Minimal but real schema: journal_number is required, extras are allowed
# (the mock placeholder document therefore validates cleanly).
TINY_SCHEMA = {
    "type": "object",
    "properties": {"journal_number": {"type": ["string", "null"]}},
    "required": ["journal_number"],
}


class TinyCase(cases.Case):
    """A self-contained case rooted in a tmp dir with in-memory records."""

    def __init__(self, root: Path, records: list[tuple[str, dict]]):
        super().__init__(name="tiny", system_prompt="You convert.", rules=["Return raw JSON only."])
        self._root = root
        self.records = records
        self.hint_files = ("hints/h.md",)

    @property
    def root(self) -> Path:
        return self._root

    def iter_records(self):
        return iter(self.records)

    def load_examples(self):
        return []


def default_records() -> list[tuple[str, dict]]:
    return [
        ("R1", {"journal_number": "R1", "value": 1}),
        ("R2", {"journal_number": "R2", "value": 1}),
        ("R3", {"journal_number": "R3", "value": 1}),
    ]


@pytest.fixture
def tiny_case(tmp_path):
    """Factory: tiny_case(records=None, hint_text='hint v1') -> TinyCase."""

    def make(records: list[tuple[str, dict]] | None = None, hint_text: str = "hint v1") -> TinyCase:
        root = tmp_path / "case"
        (root / "input" / "hints").mkdir(parents=True, exist_ok=True)
        (root / "input" / "schema.json").write_text(json.dumps(TINY_SCHEMA), encoding="utf-8")
        (root / "input" / "hints" / "h.md").write_text(hint_text, encoding="utf-8")
        return TinyCase(root, records if records is not None else default_records())

    return make


@pytest.fixture
def convert_args(tmp_path):
    """Factory for the argparse.Namespace `pipeline.run` expects (mock mode)."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"mock": {"model": "mock"}}), encoding="utf-8")

    def make(**overrides) -> argparse.Namespace:
        base = dict(case="tiny", output_dir=None, config=config_path, endpoint="openai",
                    no_examples=True, temperature=0.0, limit=None, only=None,
                    dry_run=False, mock=True)
        base.update(overrides)
        return argparse.Namespace(**base)

    return make


@pytest.fixture
def run_mock_pipeline(tiny_case, convert_args, monkeypatch):
    """Run the real pipeline end-to-end in mock mode on the tiny case.

    Returns (case, run) where run(name, **arg_overrides) executes one
    conversion into <case output>/<name> and returns that run folder."""
    import pipeline

    case = tiny_case()
    monkeypatch.setattr(pipeline, "get_case", lambda name: case)

    def run(name: str, **overrides) -> Path:
        out = case.output_dir / name
        rc = pipeline.run(convert_args(output_dir=out, **overrides))
        assert rc == 0, f"pipeline.run failed for {name} (rc={rc})"
        return out

    return case, run
