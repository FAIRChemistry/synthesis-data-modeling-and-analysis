#!/usr/bin/env python3
"""Clean a raw Chemotion ELN export into per-reaction records for the LLM.

A Chemotion export is a single JSON dump of relational tables (``Reaction``,
``Sample``, ``Molecule``, ``ReactionsStartingMaterialSample`` …). This module
resolves those joins into one self-contained, human-readable record per
reaction — the Chemotion analogue of ``preprocess.extract_workbook`` for the
Excel case. The record is what the LLM sees; the free-text procedure
(``plain_text_description`` / ``plain_text_observation``) is passed through
verbatim so the model can apply the extraction hints.

Adapted from FAIRSynthesis_MOF ``chemotion_cleaner.py`` (the pydantic
``generated_apis`` dependency is dropped in favour of plain dicts).
"""

from __future__ import annotations

from typing import Any


def _nz(value: Any) -> Any:
    """Map Chemotion's ``0``/``0.0`` "not recorded" sentinel to ``None``.

    Chemotion stores 0 for quantities it does not track (e.g. the density of a
    solid, the equivalents of a scavenger). The target schema forbids 0 for
    these fields (``exclusiveMinimum: 0``), so 0 is never a meaningful value —
    treat it as missing. Non-zero numbers and non-numeric values pass through.
    """
    if isinstance(value, bool):
        return value
    return None if value == 0 else value


def _resolve_sample(sample_id: str, samples: dict, molecules: dict, molecule_names: dict) -> dict:
    """Resolve a Chemotion sample id to a flat, readable description."""
    sample = samples.get(sample_id, {})
    molecule = molecules.get(sample.get("molecule_id"), {}) if sample.get("molecule_id") else {}
    name_entry = (
        molecule_names.get(sample.get("molecule_name_id"), {})
        if sample.get("molecule_name_id")
        else {}
    )
    name = (
        name_entry.get("name")
        or sample.get("name")
        or molecule.get("iupac_name")
        or sample.get("short_label", "")
    )
    entry = {
        "short_label": sample.get("short_label"),
        "name": name,
        "molecular_weight": _nz(molecule.get("molecular_weight")),
        "real_amount_value": _nz(sample.get("real_amount_value")),
        "real_amount_unit": sample.get("real_amount_unit"),
        "target_amount_value": _nz(sample.get("target_amount_value")),
        "target_amount_unit": sample.get("target_amount_unit"),
        "density": _nz(sample.get("density")),
    }
    # Chemotion stores these directly on Molecule.  Do not derive or look up
    # identifiers here: preserve only native, non-empty source values.
    identifiers = {
        "smiles": molecule.get("cano_smiles"),
        "inchi": molecule.get("inchistring"),
        "inchikey": molecule.get("inchikey"),
    }
    entry.update({key: value for key, value in identifiers.items() if value})
    return entry


def _sample_entry(row: dict, samples: dict, molecules: dict, molecule_names: dict) -> dict:
    entry = _resolve_sample(row.get("sample_id"), samples, molecules, molecule_names)
    entry["equivalent"] = _nz(row.get("equivalent"))
    entry["reference"] = row.get("reference", False)
    entry["position"] = row.get("position")
    return entry


def _normalize_vessel_size(vessel_size: dict | None) -> dict | None:
    if not vessel_size:
        return None
    amount, unit = vessel_size.get("amount"), vessel_size.get("unit")
    return {"amount": amount, "unit": unit} if amount is not None and unit is not None else None


# Chemotion join tables → the record section they populate.
_SECTIONS = {
    "starting_materials": "ReactionsStartingMaterialSample",
    "solvents": "ReactionsSolventSample",
    "purification_solvents": "ReactionsPurificationSolventSample",
    "products": "ReactionsProductSample",
}

def clean_and_split(export: dict) -> list[dict]:
    """Turn a raw Chemotion export into one record per reaction.

    This is a generic Chemotion join-resolver: it flattens the relational tables
    but keeps the original Chemotion field names and values (``short_label``,
    ``name``, ``created_at``, resolved sample fields, …). It does NOT map onto
    the target schema and applies no lab-specific naming conventions — that
    belongs in the case-specific hints. Records are sorted by ``short_label``.
    """
    samples = export.get("Sample", {})
    molecules = export.get("Molecule", {})
    molecule_names = export.get("MoleculeName", {})
    reactions = export.get("Reaction", {})
    records: dict[str, dict] = {}
    for rid, rxn in reactions.items():
        records[rid] = {
            "short_label": rxn.get("short_label") or rid,
            "name": rxn.get("name", ""),
            "created_at": rxn.get("created_at"),
            "status": rxn.get("status"),
            "temperature": rxn.get("temperature"),
            "duration": rxn.get("duration"),
            "vessel_size": _normalize_vessel_size(rxn.get("vessel_size")),
            "plain_text_description": rxn.get("plain_text_description"),
            "plain_text_observation": rxn.get("plain_text_observation"),
            **{section: [] for section in _SECTIONS},
        }

    for section, table in _SECTIONS.items():
        for row in export.get(table, {}).values():
            rid = row.get("reaction_id")
            if rid in records and row.get("sample_id") in samples:
                entry = _sample_entry(row, samples, molecules, molecule_names)
                records[rid][section].append(entry)

    for record in records.values():
        for section in _SECTIONS:
            record[section].sort(key=lambda entry: entry.get("position") or 0)

    return sorted(records.values(), key=lambda r: r["short_label"])


def iter_records(export: dict):
    """Yield ``(short_label, record)`` pairs for the pipeline."""
    for record in clean_and_split(export):
        yield record["short_label"], record
