"""Schema compatibility tests: every case schema is a self-contained *refinement*
of the shared root schema (schema/lab_journal.schema.json).

There is deliberately no runtime inheritance or merging — each case owns its
full schema document. These tests are what keep the schemas conceptually
aligned instead: a case may tighten the root (extra required fields, stricter
patterns, fewer step types) but must never accept a document the root rejects.

Three layers, from diagnostic to authoritative:
  1. structural checks (fast, readable: which property/required/step diverged),
  2. example documents validate against both case and root schema,
  3. a formal subschema check via ``jsonsubschema`` — decides real schema
     inclusion (case ⊑ root), catching what the structural proxies cannot
     (widened enums, relaxed bounds, untyped properties in open objects).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
ROOT_SCHEMA_PATH = ROOT / "schema" / "lab_journal.schema.json"
CASE_SCHEMA_PATHS = {
    "excel_workbooks": ROOT / "cases" / "excel_workbooks" / "input" / "schema.json",
    "chemotion_eln": ROOT / "cases" / "chemotion_eln" / "input" / "schema.json",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _step_types(schema: dict) -> set[str]:
    branches = schema["$defs"]["ProcedureSteps"]["properties"]["Step"]["items"]["oneOf"]
    return {branch["properties"]["$xml_type"]["const"] for branch in branches}


def _example_documents(case_name: str) -> list[Path]:
    """The curated target JSONs shipped as few-shot examples for a case."""
    examples_dir = CASE_SCHEMA_PATHS[case_name].parent / "examples"
    return [p for p in sorted(examples_dir.glob("*.json"))
            if not p.name.endswith(".input.json")]


@pytest.fixture(scope="module")
def root_schema() -> dict:
    return _load(ROOT_SCHEMA_PATH)


# --------------------------------------------------------------------------- #
# The schemas themselves are well-formed
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("path", [ROOT_SCHEMA_PATH, *CASE_SCHEMA_PATHS.values()],
                         ids=["root", *CASE_SCHEMA_PATHS])
def test_schema_is_valid_draft7(path):
    Draft7Validator.check_schema(_load(path))


# --------------------------------------------------------------------------- #
# Structural refinement: case schemas only tighten the root, never extend it
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("case_name", CASE_SCHEMA_PATHS, ids=CASE_SCHEMA_PATHS)
def test_case_requires_at_least_the_root_required_fields(root_schema, case_name):
    case_schema = _load(CASE_SCHEMA_PATHS[case_name])
    missing = set(root_schema["required"]) - set(case_schema["required"])
    assert not missing, f"{case_name} no longer requires root-required fields: {missing}"


@pytest.mark.parametrize("case_name", CASE_SCHEMA_PATHS, ids=CASE_SCHEMA_PATHS)
def test_case_properties_are_a_subset_of_root(root_schema, case_name):
    """The root closes its property set (additionalProperties: false), so any
    property a case introduces beyond the root would make case-valid documents
    root-invalid."""
    case_schema = _load(CASE_SCHEMA_PATHS[case_name])
    assert root_schema.get("additionalProperties") is False

    extra = set(case_schema["properties"]) - set(root_schema["properties"])
    assert not extra, f"{case_name} adds top-level properties unknown to the root: {extra}"

    # Cases may omit optional root-level fields entirely.  When they retain a
    # shared collection, its item properties must still be a subset of root.
    for field in ("products", "starting_materials", "reagent_sources"):
        if field not in case_schema["properties"]:
            continue
        case_items = case_schema["properties"][field]["items"]["properties"]
        root_items = root_schema["properties"][field]["items"]["properties"]
        extra = set(case_items) - set(root_items)
        assert not extra, f"{case_name} {field} items add properties unknown to the root: {extra}"


@pytest.mark.parametrize("case_name", CASE_SCHEMA_PATHS, ids=CASE_SCHEMA_PATHS)
def test_case_step_types_are_a_subset_of_root(root_schema, case_name):
    case_schema = _load(CASE_SCHEMA_PATHS[case_name])
    extra = _step_types(case_schema) - _step_types(root_schema)
    assert not extra, f"{case_name} defines step types unknown to the root: {extra}"


def test_chemotion_heatchill_requires_temperature_or_reflux():
    """Chemotion must not emit a condition-less HeatChill step."""
    schema = _load(CASE_SCHEMA_PATHS["chemotion_eln"])
    branches = schema["$defs"]["ProcedureSteps"]["properties"]["Step"]["items"]["oneOf"]
    heat_chill = next(branch for branch in branches
                      if branch["properties"]["$xml_type"]["const"] == "HeatChill")
    validator = Draft7Validator({"type": "object", "anyOf": heat_chill["anyOf"]})

    valid_steps = (
        {"$xml_type": "HeatChill", "_temp": {"Value": 80, "Unit": "celsius"}},
        {"$xml_type": "HeatChill", "_reflux": True},
        {"$xml_type": "HeatChill", "_temp": {"Value": 80, "Unit": "celsius"},
         "_reflux": True},
    )
    for step in valid_steps:
        assert validator.is_valid(step)

    assert not validator.is_valid({"$xml_type": "HeatChill"})
    assert not validator.is_valid({"$xml_type": "HeatChill", "_reflux": False})


def test_identifiers_are_optional_material_fields_in_root_and_cases(root_schema):
    """Structure identifiers belong to material entries, not a source-specific root field."""
    identifier_fields = {"smiles", "inchi", "inchikey"}
    assert "chemical_structures" not in root_schema["properties"]
    assert "embedded_reaction_smiles" not in root_schema["properties"]

    for schema in (root_schema, *(_load(path) for path in CASE_SCHEMA_PATHS.values())):
        for collection in ("starting_materials", "products"):
            item_schema = schema["properties"][collection]["items"]
            assert identifier_fields <= set(item_schema["properties"])
            assert not identifier_fields & set(item_schema.get("required", []))
            for field in identifier_fields:
                assert item_schema["properties"][field] == {
                    "description": item_schema["properties"][field].get("description"),
                    "minLength": 1,
                    "type": "string",
                }


# --------------------------------------------------------------------------- #
# Behavioural refinement: case-valid documents are root-valid
# --------------------------------------------------------------------------- #

_EXAMPLES = [(case, path) for case in CASE_SCHEMA_PATHS for path in _example_documents(case)]


@pytest.mark.parametrize("case_name,example", _EXAMPLES,
                         ids=[f"{c}:{p.stem[:30]}" for c, p in _EXAMPLES])
def test_case_examples_validate_against_case_and_root_schema(root_schema, case_name, example):
    document = _load(example)
    case_schema = _load(CASE_SCHEMA_PATHS[case_name])

    case_errors = list(Draft7Validator(case_schema, format_checker=FormatChecker())
                       .iter_errors(document))
    assert not case_errors, f"{example.name} vs case schema: {case_errors[0].message}"

    root_errors = list(Draft7Validator(root_schema, format_checker=FormatChecker())
                       .iter_errors(document))
    assert not root_errors, f"{example.name} vs root schema: {root_errors[0].message}"


def test_examples_were_found():
    """Guard: the compatibility check above must actually exercise documents."""
    assert len(_EXAMPLES) >= 2


# --------------------------------------------------------------------------- #
# Formal refinement: case ⊑ root, decided by jsonsubschema
# --------------------------------------------------------------------------- #
# ``jsonsubschema`` (IBM Research, ISSTA 2021) decides true schema inclusion,
# but speaks draft-04 and cannot negate object schemas (needed for oneOf).
# ``_to_checkable`` rewrites our schemas into an equivalent dialect it accepts;
# every rewrite is semantics-preserving, and the oneOf one asserts the
# precondition that makes it so.

def _to_checkable(schema: dict) -> dict:
    """Inline $refs, convert draft-07 numeric exclusiveMin/Max to draft-04
    boolean form, and rewrite the step union from oneOf to anyOf (equivalent
    because the branches are made pairwise disjoint by their $xml_type consts;
    the shared sibling properties are merged into every branch)."""
    defs = schema.get("$defs", {})

    def transform(node):
        if isinstance(node, list):
            return [transform(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = copy.deepcopy(defs[node["$ref"].split("/")[-1]])
            merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
            return transform(merged)
        if "oneOf" in node:
            consts = [branch["properties"]["$xml_type"]["const"] for branch in node["oneOf"]]
            if len(consts) != len(set(consts)):
                raise ValueError("oneOf branches are not discriminated by distinct "
                                 "$xml_type consts; the anyOf rewrite would be unsound.")
            branches = []
            for branch in node["oneOf"]:
                merged = copy.deepcopy(branch)
                merged.setdefault("type", "object")
                merged["properties"] = {**node.get("properties", {}), **merged.get("properties", {})}
                merged["required"] = sorted(set(node.get("required", [])) | set(merged.get("required", [])))
                branches.append(transform(merged))
            return {"anyOf": branches}
        out = {}
        for key, value in node.items():
            if key in ("$defs", "$id", "$comment", "$schema"):
                continue
            if key in ("exclusiveMinimum", "exclusiveMaximum") and not isinstance(value, bool):
                bound = "minimum" if key == "exclusiveMinimum" else "maximum"
                out[bound], out[key] = value, True
            else:
                out[key] = transform(value)
        return out

    return transform(schema)


@pytest.mark.parametrize("case_name", CASE_SCHEMA_PATHS, ids=CASE_SCHEMA_PATHS)
def test_case_schema_is_formal_subschema_of_root(root_schema, case_name):
    """The authoritative check: every instance the case schema accepts is also
    accepted by the root schema."""
    jsonsubschema = pytest.importorskip("jsonsubschema")
    case_schema = _load(CASE_SCHEMA_PATHS[case_name])
    assert jsonsubschema.isSubschema(_to_checkable(case_schema), _to_checkable(root_schema)), (
        f"{case_name} accepts documents the root schema rejects "
        "(it must only tighten the root, never relax it)")
