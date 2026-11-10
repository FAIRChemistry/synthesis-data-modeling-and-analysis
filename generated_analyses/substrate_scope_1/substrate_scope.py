#!/usr/bin/env python3
"""Substrate scope of the FeNO3/Selectfluor hydrofluorination (C233, C234, C238-C242).

Builds a paper-style scope table (substrate, molar mass, mass and amount used,
isolated yield) and ranks the substrates by isolated yield in a bar chart.

Dependencies: Python 3.10+, matplotlib. No pandas, no project imports - this
script is self-contained so the attempt folder reruns on its own.

Rerun:
    python3 generated_analyses/substrate_scope_1/substrate_scope.py \
        --input cases/excel_workbooks/output/run_2026_09_08_18_23/assembled \
        --output generated_analyses/substrate_scope_1/outputs

Assumptions and validation notes (see also the report in the chat log):
* The substrate is the starting material with role ``limiting_reagent`` (the
  olefin in every run of the series); the Fe salt, Selectfluor and NaBH4 are
  charged relative to it and are not scope entries.
* "Isolated yield" is the workbook's recorded yield of the main product; it is
  re-derived here from isolated mass / product molar mass / substrate amount and
  the script asserts it matches the recorded ``yield_percent`` to 0.1 pp.
* C238, C239 and C241 carry a product molar mass but no isolated mass - the
  cells are empty in the source workbooks, so the yield is not determined
  rather than zero.  They are listed in the table and shown as "n.d." rows in
  the chart, never as a 0 % bar.
* Substrate identity is the workbook's internal olefin code (HOL-180, HAU-12,
  ...); the assembled records carry no structure, so no name or SMILES is
  invented here.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SERIES = ["WAT-Ch-233", "WAT-Ch-234", "WAT-Ch-238", "WAT-Ch-239",
          "WAT-Ch-240", "WAT-Ch-241", "WAT-Ch-242"]

# Single-measure chart: one hue for the bars, neutral for the not-determined
# rows. Same reference palette as the parameter-sweep attempt.
C_BAR = "#2a78d6"
C_MUTED = "#b8b7b2"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
SURFACE = "#fcfcfb"


def load(input_dir: Path) -> dict[str, dict[str, Any]]:
    docs = {}
    for path in sorted(input_dir.glob("WAT-Ch-*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("journal_number") in SERIES:
            docs[doc["journal_number"]] = doc
    return docs


def substrate(doc: dict[str, Any]) -> dict[str, Any]:
    materials = doc.get("starting_materials") or []
    limiting = [m for m in materials if m.get("role") == "limiting_reagent"]
    if len(limiting) != 1:
        raise SystemExit(f"{doc['journal_number']}: expected one limiting reagent, got {len(limiting)}")
    return limiting[0]


def main_product(doc: dict[str, Any]) -> dict[str, Any] | None:
    products = doc.get("products") or []
    main = [p for p in products if p.get("is_main_product")] or products
    return main[0] if main else None


def build_rows(docs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for jn in SERIES:
        doc = docs.get(jn)
        if doc is None:
            print(f"  ! {jn} missing from the input folder - skipped")
            continue
        sm, prod = substrate(doc), main_product(doc)
        mmol = sm.get("amount_mmol")
        prod_mmol = prod.get("amount_mmol") if prod else None
        # Recomputed rather than trusted: catches a workbook whose yield cell
        # was typed over instead of calculated.
        recomputed = None if (prod_mmol is None or not mmol) else 100 * prod_mmol / mmol
        rows.append({
            "journal": jn,
            "label": "C" + jn.split("-")[-1],
            "date": doc.get("date"),
            "substrate": sm.get("name"),
            "substrate_M_g_mol": sm.get("molar_mass_g_mol"),
            "substrate_mass_mg": None if sm.get("mass_g") is None else sm["mass_g"] * 1000,
            "substrate_mmol": mmol,
            "product_M_g_mol": prod.get("molar_mass_g_mol") if prod else None,
            "product_mass_mg": None if not prod or prod.get("yield_g") is None else prod["yield_g"] * 1000,
            "product_mmol": prod_mmol,
            "yield_percent": prod.get("yield_percent") if prod else None,
            "yield_percent_recomputed": recomputed,
        })
    return rows


def rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Yields first, best to worst; the not-determined runs keep their run order."""
    return sorted(rows, key=lambda r: (r["yield_percent"] is None,
                                       -(r["yield_percent"] or 0), r["journal"]))


def fmt(value: Any, digits: int = 1) -> str:
    return "n.d." if value is None else f"{value:.{digits}f}"


def plot(rows: list[dict[str, Any]], path: Path) -> None:
    ordered = rank(rows)[::-1]  # matplotlib draws y upwards; best bar on top
    ys = range(len(ordered))

    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    for y, r in zip(ys, ordered):
        value = r["yield_percent"]
        if value is None:
            # A missing yield is not a zero bar: mark the row and say so.
            ax.plot(0, y, marker="|", markersize=11, color=C_MUTED, markeredgewidth=2)
            ax.text(1.4, y, "not determined (no isolated mass recorded)",
                    va="center", fontsize=9, color=INK_MUTED, style="italic")
            continue
        ax.barh(y, value, height=0.6, color=C_BAR, edgecolor=SURFACE, linewidth=1.4)
        ax.text(value + 1.4, y, f"{value:.1f} %", va="center", fontsize=9.5, color=INK)

    ax.set_yticks(list(ys))
    ax.set_yticklabels([f"{r['substrate'].replace('Olefin ', '')}  ·  {r['label']}"
                        for r in ordered], fontsize=9.5)
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", colors=INK_MUTED, labelsize=9)
    ax.set_xlim(0, 100)
    ax.set_xlabel("isolated yield / %", fontsize=10, color=INK)
    ax.set_title("FeNO₃/Selectfluor hydrofluorination: substrate scope",
                 fontsize=13, color=INK, pad=12, loc="left")
    ax.margins(y=0.06)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#d9d8d3")
    ax.grid(axis="x", linestyle=":", linewidth=0.7, color="#d9d8d3", alpha=0.9)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor=fig.get_facecolor())
    plt.close(fig)


COLUMNS = ["journal", "label", "date", "substrate", "substrate_M_g_mol",
           "substrate_mass_mg", "substrate_mmol", "product_M_g_mol",
           "product_mass_mg", "product_mmol", "yield_percent",
           "yield_percent_recomputed"]


def write_tables(rows: list[dict[str, Any]], out: Path) -> None:
    with (out / "substrate_scope.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in sorted(rows, key=lambda r: r["journal"]):
            writer.writerow({k: ("" if r.get(k) is None else
                                 round(r[k], 4) if isinstance(r.get(k), float) else r.get(k))
                             for k in COLUMNS})

    lines = [
        "# Substrate scope, FeNO₃ / Selectfluor hydrofluorination (C233, C234, C238–C242)",
        "",
        "Conditions held constant across the series: 2 eq Fe(NO₃)₃·9 H₂O, 2 eq Selectfluor,",
        "2 × 3.2 eq NaBH₄, H₂O/MeCN 2:1, addition at RT, 30 min at 0 °C.",
        "",
        "| entry | run | substrate | M / g mol⁻¹ | mass / mg | amount / mmol | product M / g mol⁻¹ | isolated / mg | isolated / mmol | isolated yield / % |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for i, r in enumerate(rank(rows), start=1):
        lines.append(
            f"| {i} | {r['label']} | {r['substrate'].replace('Olefin ', '')} "
            f"| {fmt(r['substrate_M_g_mol'], 2)} | {fmt(r['substrate_mass_mg'], 1)} "
            f"| {fmt(r['substrate_mmol'], 3)} | {fmt(r['product_M_g_mol'], 2)} "
            f"| {fmt(r['product_mass_mg'], 1)} | {fmt(r['product_mmol'], 3)} "
            f"| {fmt(r['yield_percent'], 1)} |"
        )
    lines += [
        "",
        "Entries are ranked by isolated yield. n.d. = not determined: the product",
        "row of these workbooks carries a molar mass but no isolated mass, so no",
        "yield can be given (this is a gap in the record, not a 0 % result).",
        "",
    ]
    (out / "substrate_scope.md").write_text("\n".join(lines), encoding="utf-8")


def self_check(rows: list[dict[str, Any]]) -> None:
    by = {r["label"]: r for r in rows}
    assert len(rows) == 7, f"expected 7 runs, got {len(rows)}"
    for r in rows:
        if r["yield_percent"] is not None:
            # The workbook's yield must be the one its own masses imply.
            assert abs(r["yield_percent"] - r["yield_percent_recomputed"]) < 0.1, r["label"]
        assert r["substrate"].startswith("Olefin"), r["substrate"]
    assert {l for l, r in by.items() if r["yield_percent"] is None} == {"C238", "C239", "C241"}
    # n.d. runs must never be read as zero, and must sort behind every yield.
    assert [r["label"] for r in rank(rows)][:4] == ["C242", "C234", "C233", "C240"]
    assert abs(by["C242"]["yield_percent"] - 57.0) < 0.1, by["C242"]["yield_percent"]
    assert abs(by["C233"]["substrate_mass_mg"] - 50.0) < 1e-6
    print("self-check: ok")


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="folder of assembled WAT-Ch-*.json records")
    parser.add_argument("--output", type=Path, default=here / "outputs")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    rows = build_rows(load(args.input))
    plot(rows, args.output / "substrate_scope.png")
    write_tables(rows, args.output)
    self_check(rows)

    for i, r in enumerate(rank(rows), start=1):
        print(f"  {i}. {r['label']}  {r['substrate']:<22} "
              f"{fmt(r['substrate_mass_mg'], 1):>6} mg  {fmt(r['substrate_mmol'], 3):>6} mmol  "
              f"{fmt(r['yield_percent'], 1):>5} %")
    print(f"wrote {args.output}/substrate_scope.{{png,csv,md}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
