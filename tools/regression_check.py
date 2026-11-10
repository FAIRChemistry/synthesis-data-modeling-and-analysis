#!/usr/bin/env python3
"""Regression check for two JSON output folders.

Reads an expectations file describing which changes between ``a_dir`` and
``b_dir`` are *desired* (because they fix a reviewer-reported issue) and
flags everything else as a possible regression.
Without an expectations file, every change is flagged.

Expectations file format (JSON):
    {
      "expected_changes": [
        {
          "file_pattern": "Ch-066",          # substring match on filename
          "json_path_pattern": "procedure",  # substring match on JSON path
          "note": "missing THF Add before LAH"
        },
        ...
      ],
      "expected_unchanged_files": ["Ch-068", ...]   # optional allow-list of files that must NOT change
    }

Exit code is non-zero when regressions are found.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from compare_outputs import compare_folders, _fmt, _MISSING


def load_expectations(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_is_expected(filename: str, json_path: str, expected_changes: list[dict[str, str]]) -> dict[str, str] | None:
    for entry in expected_changes:
        fp = entry.get("file_pattern", "")
        pp = entry.get("json_path_pattern", "")
        if fp and fp not in filename:
            continue
        if pp and pp not in json_path:
            continue
        return entry
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("a_dir", type=Path, help="Baseline output folder")
    parser.add_argument("b_dir", type=Path, help="New output folder")
    parser.add_argument("--expectations", type=Path,
                        help="Optional expectations JSON (default: flag every change)")
    parser.add_argument("--show-confirmed", action="store_true", help="Also list desired changes that actually happened")
    args = parser.parse_args()

    expectations = load_expectations(args.expectations) if args.expectations else {}
    expected_changes = expectations.get("expected_changes", [])
    expected_unchanged = set(expectations.get("expected_unchanged_files", []))

    results = compare_folders(args.a_dir, args.b_dir, name_filter=None)

    regressions: list[tuple[str, str, Any, Any]] = []
    confirmed: list[tuple[str, str, dict[str, str], Any, Any]] = []
    unmatched_expectations: list[dict[str, str]] = list(expected_changes)

    for filename, diffs in results.items():
        if any(token in filename for token in expected_unchanged):
            for path, before, after in diffs:
                regressions.append((filename, path, before, after))
            continue
        for path, before, after in diffs:
            match = diff_is_expected(filename, path, expected_changes)
            if match:
                confirmed.append((filename, path, match, before, after))
                if match in unmatched_expectations:
                    unmatched_expectations.remove(match)
            else:
                regressions.append((filename, path, before, after))

    if args.show_confirmed and confirmed:
        print(f"Confirmed desired changes ({len(confirmed)}):")
        for filename, path, match, before, after in confirmed:
            print(f"  [{filename}] {path}  ({match.get('note', '')})")
            print(f"    a: {_fmt(before)}")
            print(f"    b: {_fmt(after)}")
        print()

    if unmatched_expectations:
        print(f"Expectations NOT observed ({len(unmatched_expectations)}):")
        for entry in unmatched_expectations:
            print(f"  file={entry.get('file_pattern', '')!r} path={entry.get('json_path_pattern', '')!r}  {entry.get('note', '')}")
        print()

    if regressions:
        print(f"Potential regressions ({len(regressions)}):")
        for filename, path, before, after in regressions:
            print(f"  [{filename}] {path}")
            print(f"    a: {_fmt(before)}")
            print(f"    b: {_fmt(after)}")
        print()
        print(f"FAIL: {len(regressions)} unexpected change(s).")
        return 1

    print(
        f"OK: {len(confirmed)} expected change(s) observed, "
        f"{len(unmatched_expectations)} expectation(s) unmet, "
        "no regressions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
