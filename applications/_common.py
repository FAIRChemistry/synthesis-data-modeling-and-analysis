"""Tiny helpers shared by the three demo scripts."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any


JOURNAL_RE = re.compile(r"WAT-Ch-(\d+)")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").lower()


def load_all(output_dir: Path) -> dict[str, dict[str, Any]]:
    """Load Excel-series records (the original application dataset)."""
    return load_records(output_dir, "WAT-Ch-*.json")


def load_records(output_dir: Path, pattern: str = "*.json") -> dict[str, dict[str, Any]]:
    """Load converted records using their journal number as the stable key.

    ``load_all`` deliberately retains its WAT-Ch glob for the existing Excel
    applications.  Generic applications can use this helper for other cases,
    including Chemotion journals such as ``AD-R13`` and ``ZAR-438``.
    """
    docs: dict[str, dict[str, Any]] = {}
    for path in sorted(output_dir.glob(pattern)):
        doc = json.loads(path.read_text(encoding="utf-8"))
        jn = doc.get("journal_number")
        if jn:
            docs[jn] = doc
    return docs


def journal_num(journal_number: str) -> str | None:
    match = JOURNAL_RE.search(journal_number or "")
    return match.group(1) if match else None


def limiting_reagent(doc: dict[str, Any]) -> dict[str, Any] | None:
    for sm in doc.get("starting_materials") or []:
        if sm.get("role") == "limiting_reagent":
            return sm
    return None


def main_product(doc: dict[str, Any]) -> dict[str, Any] | None:
    """The main product, preferring one that actually carries a yield.

    A workbook may list the same main product twice - WAT-Ch-081 has an
    "ausgewogen" row without a yield next to a "quant" row at 100 % - and
    taking the first one blanks the yield for the whole run.
    """
    products = doc.get("products") or []
    candidates = [p for p in products if p.get("is_main_product")] or products
    for p in candidates:
        if p.get("yield_percent") is not None:
            return p
    return candidates[0] if candidates else None


def yield_percent(doc: dict[str, Any]) -> float | None:
    p = main_product(doc)
    return p.get("yield_percent") if p else None
