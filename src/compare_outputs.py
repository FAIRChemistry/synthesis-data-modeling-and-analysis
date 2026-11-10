#!/usr/bin/env python3
"""Compare two JSON output folders produced by the conversion pipeline.

Walks both folders, pairs files by name, and prints a structured diff per
file: which JSON paths changed, what value they had in ``a`` and what value
they have in ``b``. Useful for sanity-checking whether new hints/model
versions actually moved the outputs in the expected direction.

Only *semantic* differences are reported:
  * strings are NFC-normalized, so composed vs. decomposed Unicode (e.g. "ü"
    as one codepoint vs. "u" + combining diaeresis) is not flagged;
  * lists are aligned by content, so inserting/removing/reordering one element
    reports that single add/remove instead of a positional diff for every
    element after it;
  * ``--float-rtol`` can ignore numeric rounding noise.

Usage:
    compare_outputs.py run_a/assembled run_b/assembled
    compare_outputs.py a b --filter Ch-066 --paths-only
    compare_outputs.py a b --json diffs.json
    compare_outputs.py a b --float-rtol 1e-3
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterator

_MISSING = object()

# Relative tolerance for float comparison. 0 means exact. Set from the CLI so that
# pure rounding/representation noise (e.g. 0.288622023 vs 0.2886) can be ignored.
_FLOAT_RTOL = 0.0


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize(value: Any) -> Any:
    """Normalize a value for *semantic* comparison.

    Strings are NFC-normalized so that the same text encoded with composed vs.
    decomposed Unicode (e.g. "Schützung" with a precomposed "ü" vs. "u" + combining
    diaeresis) compares equal. Other types pass through unchanged.
    """
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    return value


def _semantically_equal(a: Any, b: Any) -> bool:
    if (
        _FLOAT_RTOL
        and isinstance(a, (int, float))
        and isinstance(b, (int, float))
        and not isinstance(a, bool)
        and not isinstance(b, bool)
    ):
        return math.isclose(a, b, rel_tol=_FLOAT_RTOL, abs_tol=0.0)
    return _normalize(a) == _normalize(b)


def _canonical(value: Any) -> str:
    """A hashable, normalization-aware signature used to align list elements."""

    def norm(v: Any) -> Any:
        if isinstance(v, str):
            return unicodedata.normalize("NFC", v)
        if isinstance(v, dict):
            return {k: norm(v[k]) for k in sorted(v)}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v

    return json.dumps(norm(value), ensure_ascii=False, sort_keys=True)


def file_key(path: Path) -> str:
    try:
        data = load_json(path)
    except Exception:
        return path.name
    journal_number = data.get("journal_number")
    return str(journal_number) if journal_number else path.name


def iter_diffs(a: Any, b: Any, path: str = "$") -> Iterator[tuple[str, Any, Any]]:
    if isinstance(a, dict) and isinstance(b, dict):
        keys = sorted(set(a) | set(b))
        for key in keys:
            yield from iter_diffs(a.get(key, _MISSING), b.get(key, _MISSING), f"{path}.{key}")
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            yield (path + ".__len__", len(a), len(b))
        # Align by content so that inserting/removing/reordering one element does
        # not cascade into a positional diff for every element after it.
        sig_a = [_canonical(x) for x in a]
        sig_b = [_canonical(x) for x in b]
        matcher = SequenceMatcher(None, sig_a, sig_b, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if tag == "replace":
                # Pair changed elements positionally within the block and recurse;
                # any surplus on either side is an add/remove.
                overlap = min(i2 - i1, j2 - j1)
                for k in range(overlap):
                    yield from iter_diffs(a[i1 + k], b[j1 + k], f"{path}[{i1 + k}]")
                for k in range(overlap, i2 - i1):
                    yield (f"{path}[{i1 + k}]", a[i1 + k], _MISSING)
                for k in range(overlap, j2 - j1):
                    yield (f"{path}[{j1 + k}]", _MISSING, b[j1 + k])
            elif tag == "delete":
                for k in range(i1, i2):
                    yield (f"{path}[{k}]", a[k], _MISSING)
            elif tag == "insert":
                for k in range(j1, j2):
                    yield (f"{path}[{k}]", _MISSING, b[k])
        return
    if not _semantically_equal(a, b):
        yield (path, a, b)


def _fmt(value: Any) -> str:
    if value is _MISSING:
        return "<missing>"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def compare_folders(a_dir: Path, b_dir: Path, name_filter: str | None) -> dict[str, list[tuple[str, Any, Any]]]:
    a_files = {file_key(p): p for p in a_dir.glob("*.json") if p.name != "summary.json"}
    b_files = {file_key(p): p for p in b_dir.glob("*.json") if p.name != "summary.json"}
    all_names = sorted(set(a_files) | set(b_files))
    results: dict[str, list[tuple[str, Any, Any]]] = {}
    for key in all_names:
        a_path = a_files.get(key)
        b_path = b_files.get(key)
        display_name = (b_path or a_path).name
        if name_filter and name_filter not in display_name and name_filter not in key:
            continue
        if a_path is None:
            results[display_name] = [("$", _MISSING, load_json(b_path))]
            continue
        if b_path is None:
            results[display_name] = [("$", load_json(a_path), _MISSING)]
            continue
        diffs = list(iter_diffs(load_json(a_path), load_json(b_path)))
        if diffs:
            results[display_name] = diffs
    return results


def print_summary(results: dict[str, list[tuple[str, Any, Any]]]) -> None:
    if not results:
        print("No differences.")
        return
    for name in sorted(results):
        diffs = results[name]
        if (
            len(diffs) == 1
            and diffs[0][0] == "$"
            and (diffs[0][1] is _MISSING or diffs[0][2] is _MISSING)
        ):
            before, after = diffs[0][1], diffs[0][2]
            if before is _MISSING:
                print(f"\n{name} exists only in b")
            elif after is _MISSING:
                print(f"\n{name} exists only in a")
            continue
        print(f"\n{name} ({len(diffs)} change{'s' if len(diffs) != 1 else ''})")
        for path, before, after in diffs:
            print(f"  {path}")
            print(f"    a: {_fmt(before)}")
            print(f"    b: {_fmt(after)}")


def print_paths_only(results: dict[str, list[tuple[str, Any, Any]]]) -> None:
    for name in sorted(results):
        if (
            len(results[name]) == 1
            and results[name][0][0] == "$"
            and (results[name][0][1] is _MISSING or results[name][0][2] is _MISSING)
        ):
            before, after = results[name][0][1], results[name][0][2]
            side = "only_in_b" if before is _MISSING else "only_in_a"
            print(f"{name}\t{side}")
            continue
        for path, _, _ in results[name]:
            print(f"{name}\t{path}")


def to_jsonable(results: dict[str, list[tuple[str, Any, Any]]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for name, diffs in results.items():
        if len(diffs) == 1 and diffs[0][0] == "$" and (diffs[0][1] is _MISSING or diffs[0][2] is _MISSING):
            before, after = diffs[0][1], diffs[0][2]
            out[name] = [
                {
                    "path": "$",
                    "status": "only_in_b" if before is _MISSING else "only_in_a",
                    "a": None,
                    "b": None,
                    "a_missing": before is _MISSING,
                    "b_missing": after is _MISSING,
                }
            ]
            continue
        out[name] = [
            {
                "path": path,
                "status": "changed",
                "a": None if before is _MISSING else before,
                "b": None if after is _MISSING else after,
                "a_missing": before is _MISSING,
                "b_missing": after is _MISSING,
            }
            for path, before, after in diffs
        ]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("a_dir", type=Path)
    parser.add_argument("b_dir", type=Path)
    parser.add_argument("--filter", dest="name_filter", help="Only compare files whose name contains this substring")
    parser.add_argument("--paths-only", action="store_true", help="Print only file\\tpath lines (compact)")
    parser.add_argument("--json", type=Path, help="Write machine-readable diff to this path")
    parser.add_argument(
        "--float-rtol",
        type=float,
        default=0.0,
        metavar="RTOL",
        help="Treat two numbers as equal if within this relative tolerance "
        "(e.g. 1e-3 to ignore rounding noise like 0.2886 vs 0.289). Default: exact.",
    )
    args = parser.parse_args()

    global _FLOAT_RTOL
    _FLOAT_RTOL = args.float_rtol

    if not args.a_dir.is_dir() or not args.b_dir.is_dir():
        print("Both arguments must be directories.", file=sys.stderr)
        return 2

    results = compare_folders(args.a_dir, args.b_dir, args.name_filter)

    if args.json:
        args.json.write_text(json.dumps(to_jsonable(results), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.json}")

    if args.paths_only:
        print_paths_only(results)
    else:
        print_summary(results)

    total = sum(len(v) for v in results.values())
    print(f"\nTotal: {len(results)} file(s) differ, {total} change(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
