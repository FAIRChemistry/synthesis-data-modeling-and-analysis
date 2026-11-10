"""Tests for the record-level diff tooling: semantic JSON comparison
(src/compare_outputs.py) and the side-by-side record diff page (src/diff_html.py)."""

from __future__ import annotations

import json

import compare_outputs
import diff_html


def _write_json(folder, name, data):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_iter_diffs_reports_changed_paths():
    a = {"x": 1, "nested": {"y": "old"}}
    b = {"x": 1, "nested": {"y": "new"}, "added": True}
    diffs = {path: (before, after) for path, before, after in compare_outputs.iter_diffs(a, b)}
    assert diffs["$.nested.y"] == ("old", "new")
    assert "$.added" in diffs and "$.x" not in diffs


def test_iter_diffs_aligns_lists_by_content():
    a = {"items": [{"id": 1}, {"id": 2}]}
    b = {"items": [{"id": 0}, {"id": 1}, {"id": 2}]}  # one insertion at the front
    diffs = list(compare_outputs.iter_diffs(a, b))
    # One length change + one insert — no cascading positional diffs.
    assert len(diffs) == 2
    assert any(path == "$.items[0]" and after == {"id": 0} for path, _, after in diffs)


def test_iter_diffs_ignores_unicode_composition():
    composed, decomposed = "ü", "ü"  # both render as 'ü'
    assert list(compare_outputs.iter_diffs({"s": composed}, {"s": decomposed})) == []


def test_compare_folders_pairs_by_journal_number(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write_json(a, "old_name.json", {"journal_number": "J-1", "v": 1})
    _write_json(b, "new_name.json", {"journal_number": "J-1", "v": 2})
    results = compare_outputs.compare_folders(a, b, name_filter=None)
    assert list(results) == ["new_name.json"]
    assert results["new_name.json"][0][0] == "$.v"


def test_render_diff_page_counts_and_skips_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write_json(a, "same.json", {"journal_number": "S", "v": 1})
    _write_json(b, "same.json", {"journal_number": "S", "v": 1})
    _write_json(a, "chg.json", {"journal_number": "C", "v": 1})
    _write_json(b, "chg.json", {"journal_number": "C", "v": 2})
    _write_json(b, "new.json", {"journal_number": "N"})

    a_files, b_files = diff_html.files_by_key(a), diff_html.files_by_key(b)
    pairs = [(k, a_files.get(k), b_files.get(k)) for k in sorted(set(a_files) | set(b_files))]
    page, counts = diff_html.render_diff_page("case", "run_A", "run_B", pairs)

    assert counts == {"changed": 1, "added": 1, "removed": 0, "identical": 1}
    assert 'id="rec-C"' in page and 'id="rec-N"' in page
    assert 'id="rec-S"' not in page  # identical records are summarized, not rendered
