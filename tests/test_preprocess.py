"""Tests for deterministic workbook extraction and source provenance."""

from __future__ import annotations

from openpyxl import Workbook

import preprocess


def test_extract_workbook_preserves_formulas_without_cached_values(tmp_path, monkeypatch):
    path = tmp_path / "formula.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = 2
    sheet["A2"] = "=A1*2"
    workbook.save(path)
    workbook.close()
    monkeypatch.setattr(
        preprocess,
        "extract_embedded_chemical_structures",
        lambda _path: {"reaction_smiles": None, "chemical_structures": []},
    )

    extracted = preprocess.extract_workbook(path)

    cells = {
        cell["address"]: cell
        for cell in extracted["sheets"][0]["non_empty_cells"]
    }
    assert cells["A1"]["value"] == 2
    assert "formula" not in cells["A1"]
    assert cells["A2"]["value"] is None
    assert cells["A2"]["formula"] == "=A1*2"
    assert extracted["preprocessor"]["options"]["formulas"].startswith("preserved")
