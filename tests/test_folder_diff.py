"""Unit tests for the generic folder diff engine (src/folder_diff.py)."""

from __future__ import annotations

import json

import pytest

import folder_diff


def _write(root, rel, content):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def tree_pair(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    return a, b


def _by_rel(entries):
    return {e.rel: e for e in entries}


def test_status_classification(tree_pair):
    a, b = tree_pair
    _write(a, "same.txt", "x\n"), _write(b, "same.txt", "x\n")
    _write(a, "changed.txt", "old\n"), _write(b, "changed.txt", "new\n")
    _write(a, "only_a.txt", "gone\n")
    _write(b, "nested/only_b.txt", "fresh\n")

    entries = _by_rel(folder_diff.diff_folders(a, b))
    assert entries["same.txt"].status == "identical"
    assert entries["changed.txt"].status == "changed"
    assert entries["only_a.txt"].status == "removed"
    assert entries["nested/only_b.txt"].status == "added"


def test_json_key_order_and_unicode_are_identical(tree_pair):
    a, b = tree_pair
    _write(a, "d.json", json.dumps({"a": 1, "b": "ü"}))          # decomposed ü
    _write(b, "d.json", json.dumps({"b": "ü", "a": 1}, indent=4))  # composed ü, other order
    (entry,) = folder_diff.diff_folders(a, b)
    assert entry.status == "identical"


def test_binary_files_compared_by_content(tree_pair):
    a, b = tree_pair
    _write(a, "blob.bin", b"\x00\x01\x02")
    _write(b, "blob.bin", b"\x00\x01\x03")
    (entry,) = folder_diff.diff_folders(a, b)
    assert entry.status == "changed"
    assert not entry.is_text

    page, counts = folder_diff.render_folder_diff_page("t", "A", "B", [entry])
    assert "Binary file" in page and "sha256" in page
    assert counts["changed"] == 1


def test_junk_and_ignore_patterns(tree_pair):
    a, b = tree_pair
    _write(a, ".DS_Store", b"junk"), _write(a, "diffs/x.html", "old")
    _write(b, "diffs/x.html", "new"), _write(b, "keep.txt", "k")
    entries = folder_diff.diff_folders(a, b, ignore=("diffs",))
    assert [e.rel for e in entries] == ["keep.txt"]


def test_render_page_sections_and_counts(tree_pair):
    a, b = tree_pair
    _write(a, "same.json", "{}"), _write(b, "same.json", "{}")
    _write(a, "changed.md", "one"), _write(b, "changed.md", "two")
    _write(b, "new.md", "hello")

    entries = folder_diff.diff_folders(a, b)
    page, counts = folder_diff.render_folder_diff_page(
        "mycase", "run_A", "run_B", entries, a_meta="a", b_meta="b")

    assert counts == {"changed": 1, "added": 1, "removed": 0, "identical": 1}
    assert 'id="f-changed-md"' in page and 'id="f-new-md"' in page
    assert "1 identical file(s)" in page and "same.json" in page
    assert "run_A" in page and "run_B" in page
    # Interactive bits: collapsible sections + expand/collapse controls.
    assert "<details" in page and "setAll(true)" in page


def test_diff_run_scope(tmp_path):
    run_a, run_b = tmp_path / "run_a", tmp_path / "run_b"
    for run, hint, result in ((run_a, "h1", "r1"), (run_b, "h2", "r2")):
        _write(run, "inputs/hints.md", hint)
        _write(run, "results/R1.json", json.dumps({"v": result}))
        _write(run, "diffs/view.html", f"noise {result}")

    entries, a_root, b_root = folder_diff.diff_run_scope(run_a, run_b, "inputs")
    assert (a_root, b_root) == (run_a / "inputs", run_b / "inputs")
    assert [e.rel for e in entries] == ["hints.md"]

    entries, a_root, _ = folder_diff.diff_run_scope(run_a, run_b, "outputs")
    assert a_root == run_a
    assert [e.rel for e in entries] == ["results/R1.json"]  # inputs/ and diffs/ excluded

    entries, _, _ = folder_diff.diff_run_scope(run_a, run_b, "all")
    assert [e.rel for e in entries] == ["inputs/hints.md", "results/R1.json"]  # diffs/ excluded
