"""Tests for deterministic chemical-identifier preprocessing."""

from __future__ import annotations

import chemotion
import preprocess


def test_reaction_components_assigns_roles_without_deriving_properties():
    assert preprocess._reaction_components("CC.O>Cl>CO") == [
        ("reactant", "CC"),
        ("reactant", "O"),
        ("agent", "Cl"),
        ("product", "CO"),
    ]


def test_embedded_structure_extraction_keeps_only_identifier_data(monkeypatch):
    monkeypatch.setattr(preprocess, "_cdx_payloads", lambda path: [b"VjCD0100 test"])

    def fake_obabel(args, *, input_text=None):
        if "-osmi" in args:
            return "CC>>CO\tChemDraw reaction\n"
        if "-oinchi" in args:
            return "InChI=1S/C2H6/c1-2/h1-2H3\nInChI=1S/CH4O/c1-2/h2H,1H3\n"
        if "-oinchikey" in args:
            return "OTMSDBZUPAUEDD-UHFFFAOYSA-N\nOKKJLVBELUTLKV-UHFFFAOYSA-N\n"
        raise AssertionError(args)

    monkeypatch.setattr(preprocess, "_run_obabel", fake_obabel)
    extracted = preprocess.extract_embedded_chemical_structures(None)

    assert extracted == {
        "reaction_smiles": ["CC>>CO"],
        "chemical_structures": [
            {
                "role": "reactant",
                "smiles": "CC",
                "inchi": "InChI=1S/C2H6/c1-2/h1-2H3",
                "inchikey": "OTMSDBZUPAUEDD-UHFFFAOYSA-N",
            },
            {
                "role": "product",
                "smiles": "CO",
                "inchi": "InChI=1S/CH4O/c1-2/h2H,1H3",
                "inchikey": "OKKJLVBELUTLKV-UHFFFAOYSA-N",
            },
        ],
    }
    assert "molar_mass_g_mol" not in str(extracted)


def test_excel_assigns_only_unambiguous_role_matches_without_property_derivation():
    reactant = {"role": "reactant", "smiles": "CC", "inchi": "inchi-reactant", "inchikey": "key-reactant"}
    product = {"role": "product", "smiles": "CO", "inchi": "inchi-product", "inchikey": "key-product"}
    summary = {
        "starting_material_table_rows": [{"name": "substrate", "eq": 1}],
        "product_table_rows": [{"name": "product"}],
    }

    preprocess._apply_unambiguous_structure_matches(
        [{"profile_summary": summary}], [reactant, product]
    )

    assert summary["starting_material_table_rows"][0]["smiles"] == "CC"
    assert summary["product_table_rows"][0]["inchi"] == "inchi-product"
    assert "molar_mass_g_mol" not in str(summary)


def test_chemotion_keeps_native_identifiers_on_each_resolved_material():
    export = {
        "Reaction": {"r1": {"short_label": "R1"}},
        "Sample": {"s1": {"molecule_id": "m1", "short_label": "sample"}},
        "Molecule": {
            "m1": {
                "iupac_name": "ethanol",
                "cano_smiles": "CCO",
                "inchistring": "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
                "inchikey": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
            }
        },
        "MoleculeName": {},
        "ReactionsStartingMaterialSample": {"row": {"reaction_id": "r1", "sample_id": "s1"}},
        "ReactionsSolventSample": {},
        "ReactionsPurificationSolventSample": {},
        "ReactionsProductSample": {},
    }

    material = chemotion.clean_and_split(export)[0]["starting_materials"][0]
    assert {key: material[key] for key in ("smiles", "inchi", "inchikey")} == {
        "smiles": "CCO",
        "inchi": "InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3",
        "inchikey": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
    }
