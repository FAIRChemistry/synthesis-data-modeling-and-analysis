#!/usr/bin/env python3
"""Case registry: what differs between input types (Excel, Chemotion ELN).

Everything the conversion pipeline needs that is *case-specific* lives behind a
``Case``: how to turn raw inputs into per-record dicts for the LLM, how to load
few-shot examples, the case's schema, its hints, and its system prompt / rules.
The pipeline itself is case-agnostic.

Each case owns a full, self-contained JSON Schema at ``input/schema.json`` (no
shared base + overlay merging); case designers edit that one document directly.
Conceptually every case schema is a refinement of the shared root schema at
``schema/lab_journal.schema.json`` — it may tighten it (extra required fields,
stricter patterns, fewer step types) but must never accept a document the root
rejects. That contract is enforced by ``tests/test_schemas.py``, not by
inheritance.

Layout (per case under ``cases/<name>/``):
    input/                 raw data, hints, examples, schema.json, ...
    output/run_<ts>/       conversion runs
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import chemotion
import preprocess

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_schema(schema_path: Path) -> dict:
    """Load a case's full JSON Schema document (used for the prompt and validation)."""
    return json.loads(schema_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Case base class                                                             #
# --------------------------------------------------------------------------- #

@dataclass
class Case:
    """A conversion case. Subclasses provide ``iter_records`` and ``load_examples``."""

    name: str
    system_prompt: str
    rules: list[str]

    @property
    def root(self) -> Path:
        return REPO_ROOT / "cases" / self.name

    @property
    def input_dir(self) -> Path:
        return self.root / "input"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def schema_path(self) -> Path:
        return self.input_dir / "schema.json"

    @property
    def examples_dir(self) -> Path:
        return self.input_dir / "examples"

    # Ordered list of hint files concatenated into the prompt (override).
    hint_files: tuple[str, ...] = ()

    def schema(self) -> dict:
        return load_schema(self.schema_path)

    def hints(self) -> str:
        parts = []
        for rel in self.hint_files:
            path = self.input_dir / rel
            if path.exists():
                parts.append(path.read_text(encoding="utf-8").strip())
        return "\n\n".join(p for p in parts if p)

    def iter_records(self) -> Iterable[tuple[str, dict]]:
        raise NotImplementedError

    def load_examples(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def prompt_record(self, preprocessed: dict[str, Any]) -> dict[str, Any]:
        """Return the record representation that should be sent to the model.

        The default keeps the complete preprocessed record. Cases with a
        deterministic profile may override this to omit redundant raw views;
        the complete record is still persisted in the run's intermediate/
        directory for auditing.
        """
        return preprocessed


# --------------------------------------------------------------------------- #
# Excel case                                                                  #
# --------------------------------------------------------------------------- #

_EXCEL_SYSTEM = (
    "You convert deterministic Excel extractions from organic chemistry lab "
    "journals into JSON. Return only one JSON object. Do not wrap it in "
    "Markdown. Use null for missing optional values. Do not invent values "
    "that are not in the workbook, examples, schema, or instructions."
)

_EXCEL_RULES = [
    "Use the schema property names exactly.",
    "When profile_summary is present, it is the authoritative source. Use profile_summary.starting_material_table_rows and profile_summary.product_table_rows for all field values; do NOT derive field values from non_empty_rows.",
    "If a table entry conflicts with the free-text procedure, the table entry takes precedence, including explicit repetition markers such as (xN). Use the procedure for order and qualitative details only where it does not contradict the table.",
    "In starting_material_table_rows, the column labelled 'g' maps to mass_g; the column labelled 'V mL' maps to volume_mL. If a row has 'g' but no 'V mL', set mass_g and leave volume_mL null. If a row has 'V mL' but no 'g', set volume_mL and leave mass_g null.",
    "In product_table_rows, the column labelled 'Laufmittel' maps to eluent_system. If that key is absent from a product row, eluent_system must be null.",
    "Preserve German procedure text where it appears in the workbook.",
    "Use reaction_name_from_filename as reaction_name unless a clearer workbook value exists.",
    "source_filename and reaction_name_from_filename are authoritative additional context: use them to disambiguate generic substrate words in the Vorschrift (e.g. 'Aminoester', 'Olefin', 'Alkohol') against the actual starting_materials table entries.",
    "Interpret comma decimal text such as '0,049 mol/L' as numeric values where appropriate.",
    "Rows under 'Literatur:' can be ignored when they contain no literature reference.",
    "If a reagent source appears on the Literatur row because of spreadsheet layout, still map it as a reagent source.",
    "Copy any smiles, inchi, and inchikey already present on a profile material row unchanged. embedded_reaction_structures is additional exact source context: use it only when the reactant/product mapping is unambiguous. Never calculate properties from an identifier.",
    "Return raw JSON only.",
]


@dataclass
class ExcelCase(Case):
    hint_files: tuple[str, ...] = (
        "hints/extraction_hints_current.md",
    )

    def prompt_record(self, preprocessed: dict[str, Any]) -> dict[str, Any]:
        """Keep the authoritative profile view only.

        ``non_empty_rows`` and ``non_empty_cells`` duplicate the same workbook
        content and are useful for audits, not for the model once a profile has
        successfully extracted the sheet. Unprofiled sheets retain their full
        representation as a safe fallback.
        """
        prompt_input = {
            key: preprocessed[key]
            for key in (
                "source_filename",
                "embedded_reaction_smiles",
                "embedded_reaction_structures",
            )
            if key in preprocessed
        }
        prompt_input["sheets"] = []
        for sheet in preprocessed.get("sheets", []):
            if "profile_summary" in sheet:
                prompt_sheet = {
                    "sheet_name": sheet.get("sheet_name"),
                    "profile_summary": sheet["profile_summary"],
                }
            else:
                prompt_sheet = sheet
            prompt_input["sheets"].append(prompt_sheet)
        return prompt_input

    @property
    def profile_path(self) -> Path:
        return self.input_dir / "profiles" / "lab_journal_profile.json"

    @property
    def workbooks_dir(self) -> Path:
        return self.input_dir / "workbooks"

    def iter_records(self) -> Iterable[tuple[str, dict]]:
        profile = preprocess.load_profile(self.profile_path)
        for xlsx in sorted(self.workbooks_dir.glob("*.xlsx")):
            if xlsx.name.startswith("~$"):
                continue
            yield xlsx.stem, preprocess.extract_workbook(xlsx, profile=profile)

    def load_examples(self) -> list[dict[str, Any]]:
        if not self.examples_dir.exists():
            return []
        profile = preprocess.load_profile(self.profile_path)
        examples = []
        for xlsx in sorted(self.examples_dir.glob("*.xlsx")):
            if xlsx.name.startswith("~$"):
                continue
            target = self.examples_dir / (xlsx.stem + ".json")
            if not target.exists():
                continue
            examples.append({
                "filename": xlsx.stem,
                "preprocessed_input": preprocess.extract_workbook(xlsx, profile=profile),
                "target_json": json.loads(target.read_text(encoding="utf-8")),
            })
        return examples


# --------------------------------------------------------------------------- #
# Chemotion ELN case                                                          #
# --------------------------------------------------------------------------- #

_CHEMOTION_SYSTEM = (
    "You convert cleaned Chemotion ELN reaction records from chemistry lab "
    "journals into JSON. Return only one JSON object, no Markdown. Use null for "
    "missing optional values. Extract only what the record states; never invent "
    "amounts, temperatures, times, or steps."
)

_CHEMOTION_RULES = [
    "Use the schema property names exactly, and return raw JSON only.",
    "journal_number, reaction_name and date are given verbatim in the record — copy them unchanged.",
    "Quantities (mass_g, volume_mL, amount_mmol, equivalents, molar_mass_g_mol) come from the resolved starting_materials / products entries, not from the free-text procedure.",
    "Copy native smiles, inchi, and inchikey values from resolved material entries unchanged. Do not derive an identifier or any property from a name or another identifier.",
    "Follow the extraction hints for how to read plain_text_description and plain_text_observation into procedure.Prep/Reaction/Workup.",
]


@dataclass
class ChemotionCase(Case):
    hint_files: tuple[str, ...] = ("hints/extraction_hints.md",)

    @property
    def export_path(self) -> Path:
        return self.input_dir / "exports" / "export.json"

    def iter_records(self) -> Iterable[tuple[str, dict]]:
        export = json.loads(self.export_path.read_text(encoding="utf-8"))
        yield from chemotion.iter_records(export)

    def load_examples(self) -> list[dict[str, Any]]:
        """Pair each ``<stem>.json`` target with its ``<stem>.input.json`` cleaned record."""
        if not self.examples_dir.exists():
            return []
        examples = []
        for target in sorted(self.examples_dir.glob("*.json")):
            if target.name.endswith(".input.json"):
                continue
            source = self.examples_dir / (target.stem + ".input.json")
            if not source.exists():
                continue
            examples.append({
                "filename": target.stem,
                "preprocessed_input": json.loads(source.read_text(encoding="utf-8")),
                "target_json": json.loads(target.read_text(encoding="utf-8")),
            })
        return examples


# --------------------------------------------------------------------------- #
# Registry                                                                    #
# --------------------------------------------------------------------------- #

_CASES = {
    "excel_workbooks": lambda: ExcelCase(
        name="excel_workbooks", system_prompt=_EXCEL_SYSTEM, rules=_EXCEL_RULES),
    "chemotion_eln": lambda: ChemotionCase(
        name="chemotion_eln", system_prompt=_CHEMOTION_SYSTEM, rules=_CHEMOTION_RULES),
}

DEFAULT_CASE = "excel_workbooks"


def get_case(name: str) -> Case:
    if name not in _CASES:
        available = ", ".join(_CASES)
        raise ValueError(f"Unknown case {name!r}. Available: {available}.")
    return _CASES[name]()


def available_cases() -> list[str]:
    return list(_CASES)
