"""Tests for prompt assembly and the offline mock conversion (src/convert.py)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import convert
from cases import ExcelCase
from conftest import TINY_SCHEMA


def _messages(record: dict) -> list[dict[str, str]]:
    return convert.build_prompt(record, TINY_SCHEMA, "hints", [], "sys", ["rule"])


def test_build_prompt_structure():
    messages = _messages({"journal_number": "R1"})
    assert [m["role"] for m in messages] == ["system", "user"]
    user = json.loads(messages[1]["content"])
    assert user["preprocessed_input"] == {"journal_number": "R1"}
    assert user["schema"] == TINY_SCHEMA and user["rules"] == ["rule"]


def test_excel_case_runtime_hints_exclude_archived_project_brief():
    case = ExcelCase(name="excel_workbooks", system_prompt="system", rules=[])
    assert case.hint_files == ("hints/extraction_hints_current.md",)


def test_excel_rules_give_table_entries_precedence_over_procedure_text():
    from cases import _EXCEL_RULES

    precedence_rule = next(rule for rule in _EXCEL_RULES if "takes precedence" in rule)
    assert "(xN)" in precedence_rule


def test_excel_case_prompt_record_keeps_profile_and_omits_duplicate_raw_views():
    case = ExcelCase(name="excel_workbooks", system_prompt="system", rules=[])
    record = {
        "source_filename": "record.xlsx",
        "preprocessor": {"library": "openpyxl"},
        "sheets": [{
            "sheet_name": "Sheet1",
            "non_empty_rows": [["duplicate"]],
            "non_empty_cells": [{"address": "A1", "value": "duplicate"}],
            "profile_summary": {"procedure": "source text"},
        }],
    }

    prompt_record = case.prompt_record(record)

    assert prompt_record == {
        "source_filename": "record.xlsx",
        "sheets": [{
            "sheet_name": "Sheet1",
            "profile_summary": {"procedure": "source text"},
        }],
    }
    assert "non_empty_cells" in record["sheets"][0]


def test_mock_conversion_is_deterministic_and_input_sensitive():
    config = {"model": "mock"}
    doc1, errors1, usage = convert.mock_conversion(
        _messages({"journal_number": "R1", "value": 1}), TINY_SCHEMA, config, 0.0)
    doc1_again, _, _ = convert.mock_conversion(
        _messages({"journal_number": "R1", "value": 1}), TINY_SCHEMA, config, 0.0)
    doc2, _, _ = convert.mock_conversion(
        _messages({"journal_number": "R1", "value": 2}), TINY_SCHEMA, config, 0.0)

    assert doc1 == doc1_again                # deterministic
    assert doc1 != doc2                      # a changed input changes the output
    assert doc1["journal_number"] == "R1"    # records stay pairable by key
    assert errors1 == []                     # placeholder satisfies the tiny schema
    assert usage["total_tokens"] == 0


def test_extract_json_object_handles_fences_and_prose():
    assert convert.extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert convert.extract_json_object('noise before {"a": 1} noise after') == {"a": 1}


def test_call_openai_uses_a_long_configurable_request_timeout(monkeypatch):
    created = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        @staticmethod
        def create(**_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"journal_number": "R1"}'))],
                usage=None,
            )

    monkeypatch.setattr(convert, "OpenAI", FakeOpenAI)
    convert.call_openai(_messages({"journal_number": "R1"}),
                        {"api_key": "test", "model": "gpt-5-mini"}, 1.0)
    assert created["timeout"] == convert.DEFAULT_REQUEST_TIMEOUT_SECONDS

    convert.call_openai(_messages({"journal_number": "R1"}), {
        "api_key": "test", "model": "gpt-5-mini", "request_timeout_seconds": 1_800,
    }, 1.0)
    assert created["timeout"] == 1_800.0
