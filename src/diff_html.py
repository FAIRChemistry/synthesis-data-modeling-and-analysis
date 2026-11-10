#!/usr/bin/env python3
"""Render a side-by-side, git-style HTML diff of two sets of record JSONs.

The diff alignment, hunking, side-by-side table and colours all come from the
standard library's ``difflib.HtmlDiff``; this module only turns paired record
files into pretty, comparable lines and stitches the per-record tables into one
self-contained HTML page.

Shared by ``tools/diff_viewer.py`` (compare two whole runs from the CLI) and the
conversion pipeline (auto-diff each run's freshly generated records against the
previous run's assembled output). Records are paired by ``journal_number`` via
``compare_outputs.file_key``, the same key the rest of the pipeline uses.
"""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from difflib import HtmlDiff
from pathlib import Path
from typing import Sequence

from compare_outputs import file_key

# Green (added), red (removed), amber (changed) — layered on top of difflib's
# own stylesheet so the highlight colours read like a Git diff.
_COLOR_OVERRIDES = """
    body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1b1f23; }
    h1 { font-size: 1.4rem; } h2 { font-size: 1.05rem; margin-top: 2.2rem; }
    .summary { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;
               padding: 0.8rem 1rem; margin-bottom: 1.5rem; }
    .summary table { border-collapse: collapse; }
    .summary td { padding: 0.1rem 0.9rem 0.1rem 0; }
    .badge { display: inline-block; padding: 0 0.4rem; border-radius: 4px; font-size: 0.8rem; }
    .b-changed { background: #fff3b0; } .b-added { background: #c6f6c6; }
    .b-removed { background: #f6c6c6; } .b-same { background: #eaeef2; color: #57606a; }
    nav a { margin-right: 0.8rem; white-space: nowrap; }
    .diffwrap { overflow-x: auto; border: 1px solid #d0d7de; border-radius: 6px; margin: 0.5rem 0 1rem; }
    table.diff { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                 font-size: 0.8rem; border: none; width: 100%; }
    .diff_header { background: #f6f8fa; color: #8c959f; text-align: right; }
    td.diff_header { padding-right: 0.6rem; }
    .diff_next { background: #f6f8fa; }
    .diff_add { background-color: #c6f6c6; }   /* green: present on the right */
    .diff_sub { background-color: #f6c6c6; }   /* red: present on the left   */
    .diff_chg { background-color: #fff3b0; }   /* amber: changed inline      */
    .note { color: #57606a; font-style: italic; }
"""


def files_by_key(folder: Path) -> dict[str, Path]:
    """Map each record's ``journal_number`` (or filename) to its JSON path."""
    return {file_key(p): p for p in folder.glob("*.json") if p.name != "summary.json"}


def _pretty_lines(path: Path) -> list[str]:
    """Stable, comparable text for one record: sorted keys, NFC-normalized so
    composed/decomposed Unicode (e.g. 'ü') is not spuriously flagged."""
    data = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    return unicodedata.normalize("NFC", text).splitlines()


def _anchor(key: str) -> str:
    return "rec-" + "".join(c if c.isalnum() else "-" for c in key)


def render_diff_page(
    case_name: str,
    a_label: str,
    b_label: str,
    pairs: Sequence[tuple[str, Path | None, Path | None]],
    *,
    a_meta: str = "",
    b_meta: str = "",
    full: bool = False,
    context_lines: int = 3,
) -> tuple[str, dict[str, int]]:
    """Build the HTML page. ``pairs`` is ``(record_key, a_path, b_path)`` items;
    a ``None`` path means the record is absent on that side. Returns the HTML and
    a counts dict (changed / added / removed / identical)."""
    differ = HtmlDiff(wrapcolumn=70)
    sections: list[str] = []
    nav: list[str] = []
    counts = {"changed": 0, "added": 0, "removed": 0, "identical": 0}

    for key, a_path, b_path in pairs:
        a_lines = _pretty_lines(a_path) if a_path else []
        b_lines = _pretty_lines(b_path) if b_path else []

        if a_path and not b_path:
            status, badge = "removed", '<span class="badge b-removed">only in A</span>'
        elif b_path and not a_path:
            status, badge = "added", '<span class="badge b-added">only in B (new)</span>'
        elif a_lines == b_lines:
            counts["identical"] += 1
            continue  # identical records are summarized, not rendered
        else:
            status, badge = "changed", '<span class="badge b-changed">changed</span>'
        counts[status] += 1

        anchor = _anchor(key)
        nav.append(f'<a href="#{anchor}">{key}</a>')
        table = differ.make_table(
            a_lines, b_lines, fromdesc=a_label, todesc=b_label,
            context=not full, numlines=context_lines,
        )
        sections.append(f'<h2 id="{anchor}">{key} {badge}</h2>\n'
                        f'<div class="diffwrap">{table}</div>')

    summary_rows = [
        ("Case", case_name),
        ("Run A (baseline)", f"{a_label}" + (f" &nbsp; <span class='note'>{a_meta}</span>" if a_meta else "")),
        ("Run B (new)", f"{b_label}" + (f" &nbsp; <span class='note'>{b_meta}</span>" if b_meta else "")),
        ("Records", f"{len(pairs)} compared &nbsp;·&nbsp; "
                    f"<span class='badge b-changed'>{counts['changed']} changed</span> "
                    f"<span class='badge b-added'>{counts['added']} only in B</span> "
                    f"<span class='badge b-removed'>{counts['removed']} only in A</span> "
                    f"<span class='badge b-same'>{counts['identical']} identical</span>"),
        ("Generated", datetime.now().isoformat(timespec="seconds")),
    ]
    summary_html = "<table>" + "".join(
        f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in summary_rows) + "</table>"

    if not sections:
        sections.append('<p class="note">No differences — the compared records are identical.</p>')

    styles = getattr(HtmlDiff, "_styles", "")
    legend = getattr(HtmlDiff, "_legend", "")
    return (f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>DiffViewer — {case_name}: {a_label} vs {b_label}</title>
<style>{styles}{_COLOR_OVERRIDES}</style>
</head><body>
<h1>DiffViewer — {case_name}</h1>
<div class="summary">{summary_html}</div>
<nav>{''.join(nav)}</nav>
{legend}
{''.join(sections)}
</body></html>
""", counts)
