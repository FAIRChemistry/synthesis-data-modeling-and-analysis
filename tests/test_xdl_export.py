"""Behaviour checks for the XDL serialization application."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APPLICATIONS = ROOT / "applications"
if str(APPLICATIONS) not in sys.path:
    sys.path.insert(0, str(APPLICATIONS))

import xdl_export as app  # noqa: E402


def _doc(*, with_vessels: bool = False) -> dict:
    vessel = {"_vessel": "5 mL vial"} if with_vessels else {}
    return {
        "journal_number": "SYNTHETIC-001",
        "reaction_name": "Synthetic serialization fixture",
        "starting_materials": [
            {"name": "Test substrate", "role": "limiting_reagent", "inchi": "InChI=1S/H2O/h1H2"},
            {"name": "AcN", "role": "solvent"},
            {"name": "Test oxidant", "role": "oxidant"},
        ],
        "products": [
            {"name": "Test product", "yield_percent": 42.0, "is_main_product": True},
        ],
        "procedure": {
            "Prep": {"Step": [
                {"$xml_type": "Add", "_reagent": "AcN",
                 "_amount": {"Value": 3.5, "Unit": "millilitre"}, **vessel},
            ]},
            "Reaction": {"Step": [
                {"$xml_type": "Add", "_reagent": "Test oxidant", "_dropwise": True},
            ]},
            "Workup": {"Step": [
                {"$xml_type": "Filter", "_rinse": [
                    {"name": "DCM", "amount": {"Value": 10, "Unit": "millilitre"}},
                ]},
            ]},
        },
    }


def test_serialization_is_well_formed_and_xdl_shaped():
    root = ET.fromstring(app.xdl_string(_doc()))
    assert root.tag == "XDL"
    synthesis = root.find("Synthesis")
    assert [child.tag for child in synthesis] == ["Hardware", "Metadata", "Procedure", "Reagents"]
    assert [section.tag for section in synthesis.find("Procedure")] == ["Prep", "Reaction", "Workup"]


def test_steps_keep_their_tag_and_render_quantities_as_value_unit():
    root = ET.fromstring(app.xdl_string(_doc()))
    add = root.find(".//Prep/Add")
    assert add.get("reagent") == "AcN"
    assert add.get("amount") == "3.5 millilitre"
    assert root.find(".//Reaction/Add").get("dropwise") == "true"
    assert root.find(".//Workup/Filter").get("rinse") == "DCM (10 millilitre)"


def test_records_without_vessels_get_the_implicit_reactor():
    root = ET.fromstring(app.xdl_string(_doc()))
    components = root.findall(".//Hardware/Component")
    assert [c.get("id") for c in components] == ["reactor"]
    assert {step.get("vessel") for step in root.find(".//Procedure").iter() if step.tag != "Prep"
            and step.tag not in ("Reaction", "Workup", "Procedure")} == {"reactor"}


def test_named_vessels_are_declared_and_not_overridden():
    root = ET.fromstring(app.xdl_string(_doc(with_vessels=True)))
    ids = [c.get("id") for c in root.findall(".//Hardware/Component")]
    assert ids == ["5 mL vial", "reactor"]
    assert root.find(".//Prep/Add").get("vessel") == "5 mL vial"


def test_reagent_roles_map_to_xdl_and_identifiers_carry_over():
    root = ET.fromstring(app.xdl_string(_doc()))
    reagents = {r.get("name"): r for r in root.findall(".//Reagents/Reagent")}
    assert reagents["Test substrate"].get("role") == "substrate"
    assert reagents["Test substrate"].get("inchi") == "InChI=1S/H2O/h1H2"
    assert reagents["AcN"].get("role") == "solvent"
    assert reagents["Test oxidant"].get("role") == "reagent"


def test_metadata_names_record_and_main_product():
    metadata = ET.fromstring(app.xdl_string(_doc())).find(".//Metadata")
    assert metadata.get("description") == "SYNTHETIC-001 - Synthetic serialization fixture"
    assert metadata.get("product") == "Test product"
    assert metadata.get("product_yield_percent") == "42"
