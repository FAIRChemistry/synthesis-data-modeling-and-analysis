#!/usr/bin/env python3
"""Serialize converted lab-journal records into the XDL exchange format.

The procedure part of the shared schema is deliberately XDL-aligned: every
step carries its XDL step tag in ``$xml_type`` and its XML attributes in
``_``-prefixed keys, with quantities as {Value, Unit} objects. Serialization
is therefore a deterministic mapping with no interpretation involved:

  - one ``<Synthesis>`` per record with ``<Metadata>``, ``<Hardware>``,
    ``<Procedure>`` (Prep/Reaction/Workup sections) and ``<Reagents>``
  - steps become elements named by ``$xml_type``; ``_attr`` keys become
    attributes; {Value, Unit} quantities render as ``"<value> <unit>"``
  - starting materials become ``<Reagent>`` entries (with InChI/SMILES when
    the record has them); products fill the ``<Metadata>`` block

``<Hardware>`` lists the vessels the steps name in ``_vessel``; records whose
steps carry no vessel (each experiment is one batch in one vessel) get a
single implicit component ``reactor`` that every step references.

Follows the XDL export of the FairSynthesis_MOF workflow (Neubauer et al.,
J. Chem. Inf. Model. 2026, DOI 10.1021/acs.jcim.6c00542).
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from _common import load_records, main_product

VESSEL_ID = "reactor"
SECTIONS = ["Prep", "Reaction", "Workup"]

# Lab-journal starting-material roles -> XDL reagent roles.
ROLE_MAP = {
    "limiting_reagent": "substrate",
    "catalyst": "catalyst",
    "solvent": "solvent",
}


def format_value(value: Any) -> str:
    """Render one step attribute value as an XDL attribute string."""
    if isinstance(value, dict) and "Value" in value and "Unit" in value:
        return f"{format_value(value['Value'])} {value['Unit']}"
    if isinstance(value, dict) and "name" in value:
        amount = value.get("amount")
        return f"{value['name']} ({format_value(amount)})" if amount else str(value["name"])
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "; ".join(format_value(item) for item in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def step_to_element(step: dict[str, Any]) -> ET.Element:
    elem = ET.Element(step.get("$xml_type", "Step"))
    if not step.get("_vessel"):
        elem.set("vessel", VESSEL_ID)
    for key, value in step.items():
        if not key.startswith("_") or value is None:
            continue
        elem.set(key.lstrip("_"), format_value(value))
    return elem


def reagent_to_element(material: dict[str, Any]) -> ET.Element:
    elem = ET.Element("Reagent")
    name = material.get("name") or "unnamed"
    elem.set("id", name)
    elem.set("name", name)
    elem.set("role", ROLE_MAP.get(material.get("role") or "", "reagent"))
    for key, attr in (("inchi", "inchi"), ("smiles", "smiles")):
        if material.get(key):
            elem.set(attr, str(material[key]))
    return elem


def vessels_used(doc: dict[str, Any]) -> list[str]:
    """Distinct vessels the steps will reference, in order of appearance.

    Steps that name no ``_vessel`` fall back to the implicit ``reactor``.
    """
    vessels: dict[str, None] = {}
    steps = [
        step
        for section in SECTIONS
        for step in ((doc.get("procedure") or {}).get(section) or {}).get("Step") or []
    ]
    for step in steps:
        vessels.setdefault(step.get("_vessel") or VESSEL_ID)
    return list(vessels) or [VESSEL_ID]


def record_to_xdl(doc: dict[str, Any]) -> ET.Element:
    root = ET.Element("XDL")
    synthesis = ET.SubElement(root, "Synthesis")

    hardware = ET.SubElement(synthesis, "Hardware")
    for vessel in vessels_used(doc):
        ET.SubElement(hardware, "Component", {"id": vessel, "type": vessel})

    metadata = ET.SubElement(synthesis, "Metadata")
    description = " - ".join(
        part for part in (doc.get("journal_number"), doc.get("reaction_name")) if part
    )
    if description:
        metadata.set("description", description)
    product = main_product(doc)
    if product:
        if product.get("name"):
            metadata.set("product", product["name"])
        if product.get("inchi"):
            metadata.set("product_inchi", product["inchi"])
        if product.get("yield_percent") is not None:
            metadata.set("product_yield_percent", format_value(product["yield_percent"]))

    procedure = ET.SubElement(synthesis, "Procedure")
    for section in SECTIONS:
        steps = ((doc.get("procedure") or {}).get(section) or {}).get("Step") or []
        section_elem = ET.SubElement(procedure, section)
        for step in steps:
            section_elem.append(step_to_element(step))

    reagents = ET.SubElement(synthesis, "Reagents")
    for material in doc.get("starting_materials") or []:
        reagents.append(reagent_to_element(material))

    return root


def xdl_string(doc: dict[str, Any]) -> str:
    root = record_to_xdl(doc)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("output"),
                        help="Folder of converted record JSON files (a run's assembled/ or results/).")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.output is None:
        args.output = args.input / "applications" / "xdl_export"

    args.output.mkdir(parents=True, exist_ok=True)
    docs = load_records(args.input)
    rows = []
    for jn, doc in docs.items():
        xml = xdl_string(doc)
        ET.fromstring(xml)  # well-formedness check before anything is written
        out_path = args.output / f"{jn}.xdl"
        out_path.write_text(xml, encoding="utf-8")
        step_count = sum(
            len((((doc.get("procedure") or {}).get(section) or {}).get("Step") or []))
            for section in SECTIONS
        )
        rows.append({"record": jn, "steps": step_count,
                     "reagents": len(doc.get("starting_materials") or []),
                     "file": out_path.name})

    summary_lines = ["| record | steps | reagents | file |", "| --- | --- | --- | --- |"]
    summary_lines += [
        f"| {r['record']} | {r['steps']} | {r['reagents']} | {r['file']} |" for r in rows
    ]
    (args.output / "xdl_export.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"records serialized: {len(rows)}")
    print(f"XDL files written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
