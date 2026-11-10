#!/usr/bin/env python3
"""Deterministically extract Excel workbooks for LLM conversion.

The core extraction is generic: workbook metadata, non-empty rows, non-empty
cells, and cell coordinates. Optional JSON profiles can add domain-specific
section summaries without hardcoding a particular workbook layout in Python.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import olefile
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter


_CDX_HEADER = b"VjCD0100"
_OBABEL_TIMEOUT_SECONDS = 30


def serialize_value(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
    return value


def compact_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def non_empty_row(values: tuple[Any, ...]) -> list[Any]:
    return [serialize_value(value) for value in values if value is not None]


def load_profile(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def find_label(cells: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    for cell in cells:
        if compact_text(cell["value"]) == label:
            return cell
    return None


def row_cells(cells: list[dict[str, Any]], row: int) -> list[dict[str, Any]]:
    return [cell for cell in cells if cell["row"] == row]


def value_at(cells: list[dict[str, Any]], row: int, col: int) -> Any:
    for cell in row_cells(cells, row):
        if cell["col"] == col:
            return cell["value"]
    return None


def first_value_in_row(cells: list[dict[str, Any]], row: int, min_col: int = 1) -> Any:
    for cell in row_cells(cells, row):
        if cell["col"] >= min_col and cell["value"] is not None:
            return cell["value"]
    return None


def relative_value(
    cells: list[dict[str, Any]],
    anchor: dict[str, Any] | None,
    row_offset: int = 0,
    col_offset: int = 0,
) -> Any:
    if anchor is None:
        return None
    return serialize_value(value_at(cells, anchor["row"] + row_offset, anchor["col"] + col_offset))


def resolve_row_bound(
    cells: list[dict[str, Any]],
    bound: dict[str, Any] | None,
    default: int,
) -> int:
    if not bound:
        return default
    label = bound.get("label")
    if label:
        cell = find_label(cells, label)
        if cell:
            return cell["row"] + int(bound.get("offset", 0))
    if "row" in bound:
        return int(bound["row"])
    return default


def column_mapped_rows(
    cells: list[dict[str, Any]],
    header_start_row: int,
    header_row_count: int,
    data_start_row: int,
    end_row: int | None,
) -> list[dict[str, Any]]:
    """Return data rows as dicts with each value keyed by its column header.

    Column labels are built by concatenating string values found in the header
    rows for each column (rows header_start_row .. header_start_row +
    header_row_count - 1).  Numeric values in header rows (e.g. batch volume)
    are ignored.  The first column of each data row that has no matching header
    is treated as the row name and stored under key "name".
    """
    max_row = max((cell["row"] for cell in cells), default=0)
    final_row = end_row if end_row is not None else max_row + 1

    col_parts: dict[int, list[str]] = {}
    for row in range(header_start_row, header_start_row + header_row_count):
        for cell in row_cells(cells, row):
            if isinstance(cell["value"], str):
                val = compact_text(cell["value"])
                if val:
                    col_parts.setdefault(cell["col"], []).append(val)

    labels: dict[int, str] = {col: " ".join(parts) for col, parts in col_parts.items()}

    result = []
    for row in range(data_start_row, final_row):
        row_dict: dict[str, Any] = {}
        for cell in row_cells(cells, row):
            col = cell["col"]
            label = labels.get(col)
            if label:
                row_dict[label] = serialize_value(cell["value"])
            else:
                row_dict.setdefault("name", serialize_value(cell["value"]))
        if row_dict:
            result.append(row_dict)
    return result


def rows_between(
    cells: list[dict[str, Any]],
    start_row: int,
    end_row: int | None,
    min_col: int = 1,
    ignored_labels: set[str] | None = None,
) -> list[list[Any]]:
    ignored = ignored_labels or set()
    max_row = max((cell["row"] for cell in cells), default=0)
    final_row = end_row if end_row is not None else max_row + 1
    rows: list[list[Any]] = []
    for row in range(start_row, final_row):
        values = []
        for cell in row_cells(cells, row):
            if cell["col"] < min_col:
                continue
            if compact_text(cell["value"]) in ignored:
                continue
            values.append(cell["value"])
        compact = non_empty_row(tuple(values))
        if compact:
            rows.append(compact)
    return rows


def extract_profile_summary(
    path: Path,
    cells: list[dict[str, Any]],
    profile: dict[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "profile_name": profile.get("profile_name"),
    }

    section_labels = profile.get("section_labels", {})
    label_positions = {}
    for name, label in section_labels.items():
        cell = find_label(cells, label)
        if cell:
            label_positions[name] = {
                "address": cell["address"],
                "row": cell["row"],
                "col": cell["col"],
                "label": label,
            }
    if label_positions:
        summary["label_positions"] = label_positions

    metadata = {}
    for field in profile.get("metadata_fields", []):
        name = field["name"]
        value = None
        if "label" in field:
            anchor = find_label(cells, field["label"])
            if anchor and field.get("value") == "next_in_row":
                value = serialize_value(first_value_in_row(cells, anchor["row"], anchor["col"] + 1))
            else:
                value = relative_value(
                    cells,
                    anchor,
                    int(field.get("row_offset", 0)),
                    int(field.get("col_offset", 1)),
                )
        elif "row" in field:
            value = serialize_value(
                first_value_in_row(cells, int(field["row"]), int(field.get("min_col", 1)))
            )
        elif "filename_strip_regex" in field:
            value = re.sub(field["filename_strip_regex"], "", path.stem).strip() or None
        metadata[name] = value
    if metadata:
        summary["metadata"] = metadata

    for field in profile.get("scalar_fields", []):
        anchor = find_label(cells, field["label"])
        summary[field["name"]] = relative_value(
            cells,
            anchor,
            int(field.get("row_offset", 0)),
            int(field.get("col_offset", 0)),
        )

    for field in profile.get("aligned_text_fields", []):
        anchor = find_label(cells, field["label"])
        summary[field["name"]] = relative_value(
            cells,
            anchor,
            int(field.get("row_offset", 1)),
            int(field.get("col_offset", 0)),
        )

    max_row = max((cell["row"] for cell in cells), default=0)
    for table in profile.get("table_ranges", []):
        start_row = resolve_row_bound(cells, table.get("start"), 1)
        end_row = resolve_row_bound(cells, table.get("end"), max_row + 1)

        if table.get("labeled"):
            header_rows = int(table.get("header_rows", 2))
            header_offset = int(table.get("header_start_offset", 0))
            header_start = start_row + header_offset
            data_start = start_row if header_offset < 0 else start_row + header_rows
            summary[table["name"]] = column_mapped_rows(
                cells, header_start, header_rows, data_start, end_row
            )
        else:
            min_col = int(table.get("min_col", 1))
            if "min_col_label" in table:
                min_col_cell = find_label(cells, table["min_col_label"])
                if min_col_cell:
                    min_col = min_col_cell["col"]
            summary[table["name"]] = rows_between(
                cells,
                start_row,
                end_row,
                min_col=min_col,
                ignored_labels=set(table.get("ignored_labels", [])),
            )

    return summary


def worksheet_merged_ranges(worksheet: Any) -> list[str]:
    merged_cells = getattr(worksheet, "merged_cells", None)
    if not merged_cells:
        return []
    ranges = getattr(merged_cells, "ranges", [])
    return [str(cell_range) for cell_range in ranges]


def _run_obabel(args: list[str], *, input_text: str | None = None) -> str:
    """Run Open Babel and return its text output with a useful failure message."""
    executable = shutil.which("obabel")
    if executable is None:
        raise RuntimeError(
            "Embedded ChemDraw structures were found, but Open Babel (obabel) is not installed. "
            "Install it with `brew install open-babel` before preprocessing this workbook."
        )
    try:
        result = subprocess.run(
            [executable, *args],
            input=input_text,
            text=True,
            capture_output=True,
            check=True,
            timeout=_OBABEL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Open Babel timed out after {_OBABEL_TIMEOUT_SECONDS}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(f"Open Babel could not convert the ChemDraw structure: {detail}") from exc
    return result.stdout


def _output_values(output: str) -> list[str]:
    """Strip optional Open Babel titles from one-value-per-line output."""
    return [line.split("\t", 1)[0].strip() for line in output.splitlines() if line.strip()]


def _cdx_payloads(path: Path) -> list[bytes]:
    """Read native ChemDraw CDX streams from an XLSX's embedded OLE objects."""
    payloads: list[bytes] = []
    with zipfile.ZipFile(path) as workbook_zip:
        embedded_names = sorted(
            name for name in workbook_zip.namelist()
            if name.startswith("xl/embeddings/") and name.endswith(".bin")
        )
        for name in embedded_names:
            embedded = workbook_zip.read(name)
            if not olefile.isOleFile(io.BytesIO(embedded)):
                continue
            with olefile.OleFileIO(io.BytesIO(embedded)) as ole:
                if not ole.exists("CONTENTS"):
                    continue
                contents = ole.openstream("CONTENTS").read()
            header_offset = contents.find(_CDX_HEADER)
            if header_offset >= 0:
                payloads.append(contents[header_offset:])
    return payloads


def _reaction_components(reaction_smiles: str) -> list[tuple[str, str]]:
    """Return individual molecule SMILES with their reaction-scheme role."""
    if ">>" in reaction_smiles:
        reactants, products = reaction_smiles.split(">>", 1)
        parts = (("reactant", reactants), ("product", products))
    elif reaction_smiles.count(">") == 2:
        reactants, agents, products = reaction_smiles.split(">", 2)
        parts = (("reactant", reactants), ("agent", agents), ("product", products))
    else:
        parts = (("unknown", reaction_smiles),)
    return [(role, smiles) for role, group in parts for smiles in group.split(".") if smiles]


def _identifiers_for_smiles(smiles: list[str]) -> list[dict[str, str]]:
    """Generate InChI and InChIKey for a list of already-extracted SMILES."""
    if not smiles:
        return []
    source = "\n".join(smiles) + "\n"
    inchis = _output_values(_run_obabel(["-ismi", "-oinchi"], input_text=source))
    inchikeys = _output_values(_run_obabel(["-ismi", "-oinchikey"], input_text=source))
    if len(inchis) != len(smiles) or len(inchikeys) != len(smiles):
        raise RuntimeError("Open Babel returned an incomplete identifier set for the ChemDraw structures")
    return [
        {"smiles": molecule_smiles, "inchi": inchi, "inchikey": inchikey}
        for molecule_smiles, inchi, inchikey in zip(smiles, inchis, inchikeys, strict=True)
    ]


def extract_embedded_chemical_structures(path: Path) -> dict[str, list[Any]]:
    """Extract CDX reaction schemes as canonical molecule identifiers.

    Excel stores the diagrams in this corpus as OLE-wrapped native ChemDraw
    streams.  Reading those streams preserves the chemical graph and avoids
    lossy optical structure recognition.  The returned entries are deliberately
    unlabelled: a scheme's left/right molecules are not reliably tied to a
    particular text-table row by the file format.
    """
    reaction_smiles: list[str] = []
    structures: list[dict[str, str]] = []
    for payload in _cdx_payloads(path):
        with tempfile.NamedTemporaryFile(suffix=".cdx") as cdx_file:
            cdx_file.write(payload)
            cdx_file.flush()
            reactions = _output_values(_run_obabel(["-icdx", cdx_file.name, "-osmi"]))
        for reaction in reactions:
            reaction_smiles.append(reaction)
            components = _reaction_components(reaction)
            # A ChemDraw attachment point is represented as ``*``. It is not a
            # complete molecule, so it has no valid InChI/InChIKey and must not
            # become a partial material identifier.
            components = [(role, smiles) for role, smiles in components if "*" not in smiles]
            identifiers = _identifiers_for_smiles([smiles for _, smiles in components])
            structures.extend(
                {"role": role, **identifier}
                for (role, _), identifier in zip(components, identifiers, strict=True)
            )
    return {"reaction_smiles": reaction_smiles, "chemical_structures": structures}


def _copy_identifiers(target: dict[str, Any], structure: dict[str, str]) -> None:
    """Copy the complete, source-extracted identifier triple to a table row."""
    target.update({key: structure[key] for key in ("smiles", "inchi", "inchikey")})


def _apply_unambiguous_structure_matches(
    sheets: list[dict[str, Any]], structures: list[dict[str, str]],
) -> None:
    """Attach only direct role/cardinality matches to profile material rows.

    This intentionally uses neither molecular mass nor a name lookup.  A single
    reactant has an unambiguous home only when the spreadsheet has one limiting
    reagent (``eq = 1``); a single product only when the product table has one
    row.  Every other extracted structure remains in the source context for
    review rather than being assigned speculatively.
    """
    summaries = [sheet.get("profile_summary", {}) for sheet in sheets]
    reactants = [item for item in structures if item["role"] == "reactant"]
    limiting_reagents = [
        row
        for summary in summaries
        for row in summary.get("starting_material_table_rows", [])
        if row.get("eq") == 1
    ]
    if len(reactants) == len(limiting_reagents) == 1:
        _copy_identifiers(limiting_reagents[0], reactants[0])

    products = [item for item in structures if item["role"] == "product"]
    product_rows = [
        row for summary in summaries for row in summary.get("product_table_rows", [])
    ]
    if len(products) == len(product_rows) == 1:
        _copy_identifiers(product_rows[0], products[0])


def extract_workbook(path: Path, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    formula_workbook = load_workbook(path, data_only=False, read_only=True)
    try:
        sheets = []
        for worksheet, formula_worksheet in zip(
            workbook.worksheets, formula_workbook.worksheets, strict=True,
        ):
            cells: list[dict[str, Any]] = []
            rows: list[list[Any]] = []
            for row, formula_row in zip(
                worksheet.iter_rows(), formula_worksheet.iter_rows(), strict=True,
            ):
                raw_values = tuple(cell.value for cell in row)
                compact = non_empty_row(raw_values)
                if compact:
                    rows.append(compact)
                for cell, formula_cell in zip(row, formula_row, strict=True):
                    formula = (
                        formula_cell.value
                        if formula_cell.data_type == "f"
                        else None
                    )
                    if cell.value is None and formula is None:
                        continue
                    extracted_cell = {
                        "address": f"{get_column_letter(cell.column)}{cell.row}",
                        "row": cell.row,
                        "col": cell.column,
                        "value": serialize_value(cell.value),
                        "python_type": type(cell.value).__name__,
                    }
                    if formula is not None:
                        extracted_cell["formula"] = formula
                    cells.append(extracted_cell)

            sheet_data = {
                "sheet_name": worksheet.title,
                "max_row": worksheet.max_row,
                "max_column": worksheet.max_column,
                "merged_ranges": worksheet_merged_ranges(worksheet),
                "non_empty_rows": rows,
                "non_empty_cells": cells,
            }
            if profile:
                # Profile extraction continues to describe displayed/cached
                # workbook values. Formula-only cells stay in non_empty_cells
                # for auditing but must not create artificial empty table rows.
                value_cells = [cell for cell in cells if cell["value"] is not None]
                profile_summary = extract_profile_summary(path, value_cells, profile)
                sheet_data["profile_summary"] = profile_summary
            sheets.append(sheet_data)
    finally:
        workbook.close()
        formula_workbook.close()

    options = {
        "data_only": True,
        "read_only": True,
        "formulas": "preserved alongside cached values in non_empty_cells",
        "formatting_images_and_charts": "not extracted",
    }
    if profile:
        options["profile_name"] = profile.get("profile_name")

    result = {
        "source_file": str(path),
        "source_filename": path.name,
        "preprocessor": {
            "library": "openpyxl",
            "mode": "profile" if profile else "generic",
            "options": options,
        },
        "sheets": sheets,
    }
    embedded_structures = extract_embedded_chemical_structures(path)
    if embedded_structures["reaction_smiles"]:
        _apply_unambiguous_structure_matches(sheets, embedded_structures["chemical_structures"])
        result["embedded_reaction_smiles"] = embedded_structures["reaction_smiles"]
        result["embedded_reaction_structures"] = embedded_structures["chemical_structures"]
        result["preprocessor"]["options"]["embedded_chemdraw"] = "extracted as CDX via Open Babel"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract deterministic JSON from an Excel workbook."
    )
    parser.add_argument("excel_file", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--profile",
        type=Path,
        help="Optional JSON profile that adds layout-specific summaries.",
    )
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args()

    data = extract_workbook(args.excel_file, profile=load_profile(args.profile))
    text = json.dumps(data, ensure_ascii=False, indent=args.indent)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
