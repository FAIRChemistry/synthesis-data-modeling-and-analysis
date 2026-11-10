#!/usr/bin/env python3
"""Generic, git-style diff between two folders, rendered as text or HTML.

This module knows nothing about runs or cases: give it two directory trees and
it walks them recursively, pairs files by relative path, and classifies each
pair as identical / changed / only-in-A / only-in-B. Nothing is hardcoded about
the folder contents, so new files added to a run are picked up automatically.

All diff logic comes from the standard library: file equality via ``filecmp``,
line alignment / hunking / the side-by-side HTML table via ``difflib.HtmlDiff``
(the same renderer ``diff_html.py`` uses for record diffs). This module only
walks the trees and prepares comparable text. JSON files are pretty-printed
with sorted keys and NFC-normalized before comparing, so key order and Unicode
composition do not produce spurious changes. Binary files (e.g. ``.xlsx``
workbooks) are compared by content and reported with size and hash when they
differ.

Used by ``cli.py diff`` and the conversion pipeline (which auto-writes the
input/output folder diffs vs the previous run) to compare two run folders;
``RUN_DIFF_SCOPES`` / ``diff_run_scope`` are the only run-layout-aware pieces.
"""

from __future__ import annotations

import filecmp
import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import HtmlDiff
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable, Sequence

# Suffixes always treated as text; anything else is sniffed by UTF-8 decoding.
_TEXT_SUFFIXES = {
    ".json", ".md", ".txt", ".csv", ".tsv", ".py", ".html", ".htm",
    ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log",
}

STATUSES = ("changed", "added", "removed", "identical")

# OS/editor junk that never counts as run content.
_JUNK_PATTERNS = (".DS_Store", "Thumbs.db", "~$*", "*.pyc", "__pycache__")


@dataclass
class FileDiff:
    """One paired file in the folder diff. ``a_path``/``b_path`` is ``None``
    when the file exists only on the other side."""

    rel: str
    status: str  # one of STATUSES ("added" = only in B, "removed" = only in A)
    a_path: Path | None
    b_path: Path | None
    is_text: bool


def _ignored(rel: str, ignore: Iterable[str]) -> bool:
    """True if the relative path matches an ignore pattern. A pattern matches
    the whole path (fnmatch) or any single path component, so ``"diffs"``
    ignores the ``diffs/`` folder anywhere in the tree."""
    parts = rel.split("/")
    return any(
        fnmatch(rel, pattern) or any(fnmatch(part, pattern) for part in parts)
        for pattern in ignore
    )


def collect_files(root: Path, ignore: Iterable[str] = ()) -> dict[str, Path]:
    """Map relative POSIX path -> absolute path for every file under ``root``."""
    if not root.is_dir():
        return {}
    files: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not _ignored(rel, _JUNK_PATTERNS) and not _ignored(rel, ignore):
            files[rel] = path
    return files


def is_text_file(path: Path) -> bool:
    if path.suffix.lower() in _TEXT_SUFFIXES:
        return True
    chunk = path.read_bytes()[:4096]
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
        return True
    except UnicodeDecodeError as exc:
        # A decode error in the last bytes may just be a truncated multi-byte
        # character from the 4 KiB sample; anywhere earlier means binary.
        return exc.start >= len(chunk) - 4


def file_lines(path: Path) -> list[str]:
    """Comparable, display-ready lines for one text file. JSON is re-serialized
    with sorted keys; everything is NFC-normalized so composed vs. decomposed
    Unicode (e.g. 'ü') is not flagged as a change."""
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2, sort_keys=True)
        except json.JSONDecodeError:
            pass  # malformed JSON diffs as plain text
    return unicodedata.normalize("NFC", text).splitlines()


def _describe_binary(path: Path) -> str:
    data = path.read_bytes()
    return f"{len(data):,} bytes, sha256 {hashlib.sha256(data).hexdigest()[:12]}"


def diff_folders(a_root: Path, b_root: Path, ignore: Iterable[str] = ()) -> list[FileDiff]:
    """Walk both trees and classify every file present on either side."""
    a_files = collect_files(a_root, ignore)
    b_files = collect_files(b_root, ignore)
    entries: list[FileDiff] = []
    for rel in sorted(set(a_files) | set(b_files)):
        a_path, b_path = a_files.get(rel), b_files.get(rel)
        is_text = is_text_file(b_path or a_path)
        if a_path is None:
            status = "added"
        elif b_path is None:
            status = "removed"
        elif filecmp.cmp(a_path, b_path, shallow=False):
            status = "identical"
        elif is_text and file_lines(a_path) == file_lines(b_path):
            status = "identical"  # only formatting / key order / encoding differs
        else:
            status = "changed"
        entries.append(FileDiff(rel, status, a_path, b_path, is_text))
    return entries


# What each run-diff scope compares, relative to the run folders. A run's own
# diffs/ folder is always excluded: it references *that run's* previous run,
# so comparing it across runs is pure noise.
RUN_DIFF_SCOPES = {
    "inputs": {"subdir": "inputs", "ignore": ()},
    "outputs": {"subdir": None, "ignore": ("inputs", "diffs")},
    "all": {"subdir": None, "ignore": ("diffs",)},
}


def diff_run_scope(a_run: Path, b_run: Path, scope: str) -> tuple[list[FileDiff], Path, Path]:
    """Diff two run folders under one of ``RUN_DIFF_SCOPES``. Returns the
    entries plus the actual roots compared (for labelling)."""
    spec = RUN_DIFF_SCOPES[scope]
    subdir = spec["subdir"]
    a_root = a_run / subdir if subdir else a_run
    b_root = b_run / subdir if subdir else b_run
    return diff_folders(a_root, b_root, ignore=spec["ignore"]), a_root, b_root


def count_statuses(entries: Sequence[FileDiff]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for entry in entries:
        counts[entry.status] += 1
    return counts


# --------------------------------------------------------------------------- #
# Text output                                                                 #
# --------------------------------------------------------------------------- #

def print_summary(entries: Sequence[FileDiff]) -> None:
    """Git-status-like console summary: one line per differing file, identical
    files only counted."""
    labels = {"changed": "changed", "added": "only in B", "removed": "only in A"}
    for entry in entries:
        if entry.status == "identical":
            continue
        note = "" if entry.is_text else "  [binary]"
        print(f"  {labels[entry.status]:>9}  {entry.rel}{note}")
    counts = count_statuses(entries)
    print(f"  {counts['changed']} changed, {counts['added']} only in B, "
          f"{counts['removed']} only in A, {counts['identical']} identical")


# --------------------------------------------------------------------------- #
# HTML output                                                                 #
# --------------------------------------------------------------------------- #

# Same visual language as diff_html.py: green added, red removed, amber changed,
# difflib's side-by-side tables — plus collapsible per-file <details> sections.
_STYLES = """
    body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1b1f23; }
    h1 { font-size: 1.4rem; }
    .summary { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;
               padding: 0.8rem 1rem; margin-bottom: 1.2rem; }
    .summary table { border-collapse: collapse; }
    .summary td { padding: 0.1rem 0.9rem 0.1rem 0; }
    .badge { display: inline-block; padding: 0 0.4rem; border-radius: 4px; font-size: 0.8rem; }
    .b-changed { background: #fff3b0; } .b-added { background: #c6f6c6; }
    .b-removed { background: #f6c6c6; } .b-same { background: #eaeef2; color: #57606a; }
    .toolbar { margin: 0.6rem 0 1rem; }
    .toolbar button { font-size: 0.8rem; padding: 0.2rem 0.7rem; margin-right: 0.5rem;
                      border: 1px solid #d0d7de; border-radius: 6px; background: #f6f8fa; cursor: pointer; }
    nav { margin-bottom: 1rem; } nav a { margin-right: 0.8rem; white-space: nowrap; font-size: 0.9rem; }
    details.file { border: 1px solid #d0d7de; border-radius: 6px; margin: 0.6rem 0; }
    details.file > summary { cursor: pointer; padding: 0.45rem 0.8rem; background: #f6f8fa;
                             font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.85rem; }
    details.file[open] > summary { border-bottom: 1px solid #d0d7de; }
    details.file > .body { padding: 0.6rem 0.8rem; }
    .diffwrap { overflow-x: auto; }
    table.diff { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                 font-size: 0.8rem; border: none; width: 100%; }
    .diff_header { background: #f6f8fa; color: #8c959f; text-align: right; }
    td.diff_header { padding-right: 0.6rem; }
    .diff_next { background: #f6f8fa; }
    .diff_add { background-color: #c6f6c6; }   /* green: present on the right */
    .diff_sub { background-color: #f6c6c6; }   /* red: present on the left   */
    .diff_chg { background-color: #fff3b0; }   /* amber: changed inline      */
    .note { color: #57606a; font-style: italic; }
    ul.filelist { columns: 2; margin: 0.4rem 0; font-family: ui-monospace, Menlo, monospace; font-size: 0.8rem; }
"""

_SCRIPT = """
    function setAll(open) {
      document.querySelectorAll('details.file').forEach(d => d.open = open);
    }
"""

_BADGES = {
    "changed": '<span class="badge b-changed">changed</span>',
    "added": '<span class="badge b-added">only in B (new)</span>',
    "removed": '<span class="badge b-removed">only in A</span>',
}


def _anchor(rel: str) -> str:
    return "f-" + "".join(c if c.isalnum() else "-" for c in rel)


def _file_body(entry: FileDiff, differ: HtmlDiff, a_label: str, b_label: str,
               full: bool, context_lines: int) -> str:
    if not entry.is_text:
        a_note = _describe_binary(entry.a_path) if entry.a_path else "absent"
        b_note = _describe_binary(entry.b_path) if entry.b_path else "absent"
        return (f'<p class="note">Binary file — A: {a_note} &nbsp;|&nbsp; B: {b_note}</p>')
    a_lines = file_lines(entry.a_path) if entry.a_path else []
    b_lines = file_lines(entry.b_path) if entry.b_path else []
    # One-sided files are rendered in full (context hunks make no sense there).
    one_sided = not (entry.a_path and entry.b_path)
    table = differ.make_table(
        a_lines, b_lines, fromdesc=a_label, todesc=b_label,
        context=not (full or one_sided), numlines=context_lines,
    )
    return f'<div class="diffwrap">{table}</div>'


def render_folder_diff_page(
    title: str,
    a_label: str,
    b_label: str,
    entries: Sequence[FileDiff],
    *,
    a_meta: str = "",
    b_meta: str = "",
    full: bool = False,
    context_lines: int = 3,
) -> tuple[str, dict[str, int]]:
    """Build one self-contained interactive HTML page for a folder diff:
    per-file collapsible sections with side-by-side diffs, a nav over the
    differing files, and identical files listed compactly. Returns the HTML
    and the status counts."""
    differ = HtmlDiff(wrapcolumn=70)
    counts = count_statuses(entries)
    sections: list[str] = []
    nav: list[str] = []
    identical: list[str] = []

    for entry in entries:
        if entry.status == "identical":
            identical.append(entry.rel)
            continue
        anchor = _anchor(entry.rel)
        nav.append(f'<a href="#{anchor}">{entry.rel}</a>')
        body = _file_body(entry, differ, a_label, b_label, full, context_lines)
        sections.append(
            f'<details class="file" id="{anchor}" open>'
            f'<summary>{entry.rel} {_BADGES[entry.status]}</summary>'
            f'<div class="body">{body}</div></details>'
        )

    if identical:
        items = "".join(f"<li>{rel}</li>" for rel in identical)
        sections.append(
            f'<details class="file"><summary>{len(identical)} identical file(s) '
            f'<span class="badge b-same">identical</span></summary>'
            f'<div class="body"><ul class="filelist">{items}</ul></div></details>'
        )
    if not entries:
        sections.append('<p class="note">No files found on either side.</p>')
    elif counts["changed"] + counts["added"] + counts["removed"] == 0:
        sections.insert(0, '<p class="note">No differences — all compared files are identical.</p>')

    summary_rows = [
        ("Compared", title),
        ("A (baseline)", a_label + (f" &nbsp; <span class='note'>{a_meta}</span>" if a_meta else "")),
        ("B (new)", b_label + (f" &nbsp; <span class='note'>{b_meta}</span>" if b_meta else "")),
        ("Files", f"{len(entries)} compared &nbsp;·&nbsp; "
                  f"<span class='badge b-changed'>{counts['changed']} changed</span> "
                  f"<span class='badge b-added'>{counts['added']} only in B</span> "
                  f"<span class='badge b-removed'>{counts['removed']} only in A</span> "
                  f"<span class='badge b-same'>{counts['identical']} identical</span>"),
        ("Generated", datetime.now().isoformat(timespec="seconds")),
    ]
    summary_html = "<table>" + "".join(
        f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in summary_rows) + "</table>"

    styles = getattr(HtmlDiff, "_styles", "")
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>RunDiff — {title}: {a_label} vs {b_label}</title>
<style>{styles}{_STYLES}</style>
<script>{_SCRIPT}</script>
</head><body>
<h1>RunDiff — {title}</h1>
<div class="summary">{summary_html}</div>
<div class="toolbar">
  <button onclick="setAll(true)">Expand all</button>
  <button onclick="setAll(false)">Collapse all</button>
</div>
<nav>{''.join(nav)}</nav>
{''.join(sections)}
</body></html>
"""
    return page, counts
