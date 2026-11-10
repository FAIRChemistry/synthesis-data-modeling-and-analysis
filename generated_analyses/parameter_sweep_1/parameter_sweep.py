"""Parameter sweep WAT-Ch-113..134: isolated-yield difference vs. the C133 standard.

Changed parameters are detected by diffing features extracted from the assembled
JSON records (schema: run_.../inputs/schema_used.json) against C133, not from titles.
"""
import argparse
import csv
import json
import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "cases/excel_workbooks/output/run_2026_09_25_10_47"
OUT = Path(__file__).resolve().parent / "outputs"
STANDARD = 133
RUNS = range(113, 135)

# Feature -> (category, label template). Order = priority when several features change.
FEATURES = {
    "selectfluor_eq": ("Selectfluor", "{} → {} eq"),
    "nabh4_eq_total": ("NaBH$_4$ amount", "{} → {} eq total"),
    "nabh4_portions": ("NaBH$_4$ portions", "{} → {} portion(s), same total"),
    "fe_eq": ("Fe(III) oxalate", "{} → {} eq"),
    "addition_temp_C": ("Addition temp.", "{} → {} °C"),
    "atmosphere": ("Atmosphere", "{} → {}"),
    "extraction_solvent": ("Extraction solvent", "{} → {}"),
    "h2o_mecn_mL": ("H$_2$O / MeCN", "H2O/MeCN {} → {} mL"),
    # Below: changes outside the requested parameter list
    "fe_salt": ("Other", "Fe salt: {} → {}"),
    "nh4oh_mL": ("Other", "NH$_4$OH quench {} → {} mL"),
    "washes": ("Other", "washes: {} → {}"),
}
# Changes that only follow from the primary change (reported in CSV, not used for categorising).
SECONDARY = {"reaction_temp_C"}


def steps(d, phase):
    return ((d.get("procedure") or {}).get(phase) or {}).get("Step") or []


def r(x):
    return round(x, 1) if isinstance(x, float) else x


def features(d):
    sm = d["starting_materials"]
    by_role = lambda role: next(s for s in sm if s["role"] == role)
    nabh4_adds = [s for s in steps(d, "Reaction") if s["$xml_type"] == "Add" and "NaBH4" in s["_reagent"]]
    adds = [s for p in ("Prep", "Reaction") for s in steps(d, p) if s["$xml_type"] == "Add"]
    vol = lambda key: sum(s["_amount"]["Value"] for s in adds if key in s["_reagent"] and s["_amount"]["Unit"] == "millilitre")
    gas = [s for s in steps(d, "Prep") if s["$xml_type"] == "EvacuateAndRefill"]
    degassed = any(s.get("_degassed") for s in adds)
    temps = lambda p: [s["_temp"]["Value"] for s in steps(d, p) if s["$xml_type"] == "HeatChill"]
    workup = steps(d, "Workup")
    fe = by_role("catalyst")
    return {
        "selectfluor_eq": r(by_role("oxidant")["equivalents"]),
        # ponytail: record 'equivalents' is per portion (amount per Add step), so total = eq × portions
        "nabh4_eq_total": r(by_role("reductant")["equivalents"] * len(nabh4_adds)),
        "nabh4_portions": len(nabh4_adds),
        "fe_eq": r(fe["equivalents"]),
        "fe_salt": "Fe(NO3)3" if "NO3" in fe["name"] else "Fe oxalate",
        "addition_temp_C": temps("Prep")[-1],
        "reaction_temp_C": temps("Reaction")[-1],
        "atmosphere": ("+".join(s["_gas"] for s in gas) + (" sparge" if gas and not gas[0].get("_time") else "")
                       + (", all solvents degassed" if degassed else "")),
        "extraction_solvent": next(s["_solvent"] for s in workup if s["$xml_type"] == "Extract"),
        "h2o_mecn_mL": f"{vol('H2O'):.1f}/{vol('AcN'):.1f}",
        "nh4oh_mL": r(next(s["_amount"]["Value"] for s in workup if s["$xml_type"] == "Add" and "NH4OH" in s["_reagent"])),
        "washes": "; ".join(f"{s['_solution']} ×{s.get('_repeat', 1)}" for s in workup if s["$xml_type"] == "WashPhase") or "none",
    }


def main_product(d):
    p = next(p for p in d["products"] if p["is_main_product"])
    lim = next(s for s in d["starting_materials"] if s["role"] == "limiting_reagent")
    if p["yield_g"] is None or p["yield_percent"] is None:
        return None, lim, "no isolated yield recorded"
    recomputed = p["yield_g"] / p["molar_mass_g_mol"] * 1000 / lim["amount_mmol"] * 100
    if not math.isclose(recomputed, p["yield_percent"], rel_tol=1e-3):
        return None, lim, (f"{p['name']} yield_percent {p['yield_percent']:.1f} inconsistent with "
                           f"{p['yield_g'] * 1000:.0f} mg / {p['molar_mass_g_mol']} g/mol ({recomputed:.1f} %); excluded")
    return p["yield_percent"], lim, ""


def load(input_dir):
    recs = {}
    for f in input_dir.glob("WAT-Ch-*.json"):
        n = int(re.match(r"WAT-Ch-(\d+)", f.name)[1])
        if n in RUNS:
            recs[n] = json.loads(f.read_text())
    return recs


def analyse(recs):
    std = recs[STANDARD]
    std_f = features(std)
    std_y = main_product(std)[0]
    rows = []
    for n, d in sorted(recs.items()):
        if n == STANDARD:
            continue
        f = features(d)
        diff = {k: (std_f[k], v) for k, v in f.items() if v != std_f[k]}
        primary = [k for k in FEATURES if k in diff]
        assert primary, f"C{n}: no parameter difference to C{STANDARD} detected"
        cat, tmpl = FEATURES[primary[0]]
        y, lim, issue = main_product(d)
        rows.append({
            "run": f"C{n}",
            "journal_number": d["journal_number"],
            "reaction_name": d["reaction_name"],
            "category": cat.replace("$", "").replace("_", ""),
            "_category_tex": cat,
            "changed_parameter": tmpl.format(*diff[primary[0]]),
            "all_differences": "; ".join(f"{k}: {a} → {b}" for k, (a, b) in diff.items()),
            "confounded": "yes" if [k for k in diff if k != primary[0] and k not in SECONDARY] else "no",
            "isolated_yield_percent": None if y is None else round(y, 2),
            "standard_yield_percent": round(std_y, 2),
            "delta_yield_pp": None if y is None else round(y - std_y, 2),
            "data_issue": issue,
            "substrate_label": lim["name"],
            "observations": d.get("observations") or "",
        })
    order = list(dict.fromkeys(c for c, _ in FEATURES.values()))
    rows.sort(key=lambda x: (order.index(x["_category_tex"]), x["run"]))
    return rows, std_y, std


def impure(row):
    return bool(re.search(r"verunreinigt|EtOAc", row["observations"]))


def tex(label):
    for a, b in (("N2", "N$_2$"), ("O2", "O$_2$"), ("Fe(NO3)3", "Fe(NO$_3$)$_3$"), ("Wasser", "water"),
                 ("H2O/MeCN", "H$_2$O/MeCN")):
        label = label.replace(a, b)
    return label


def plot(rows, std_y, path):
    plt.rcParams.update({"font.size": 7, "font.family": "sans-serif", "axes.linewidth": 0.6})
    w = 7.0  # in, double-column journal width
    fig, ax = plt.subplots(figsize=(w, w * 0.62))
    y, ys, prev, groups = 0.0, [], None, []
    for row in rows:
        if prev is not None and row["_category_tex"] != prev:
            y += 0.6
        if row["_category_tex"] != prev:
            groups.append([row["_category_tex"], y, y])
        groups[-1][2] = y
        ys.append(y)
        prev = row["_category_tex"]
        y += 1
    d = [row["delta_yield_pp"] for row in rows]
    colors = ["#2a78d6" if (v or 0) >= 0 else "#e34948" for v in d]
    ax.barh(ys, [v or 0 for v in d], height=0.7, color=colors, edgecolor="white", linewidth=0.5, zorder=2)
    ax.axvline(0, color="#555", lw=0.8, zorder=3)
    for yi, v, row in zip(ys, d, rows):
        if v is None:
            ax.text(-0.6, yi, "n/a (no valid product yield)", va="center", ha="right", fontsize=6.5, color="#777", style="italic")
        else:
            ax.text(v + (0.6 if v >= 0 else -0.6), yi, f"{v:+.1f}{'†' if impure(row) else ''}", va="center",
                    ha="left" if v >= 0 else "right", fontsize=6.5, color="#333")
    ax.set_yticks(ys, [f"{row['run']}  {tex(row['changed_parameter'])}" for row in rows])
    ax.tick_params(axis="y", length=0)
    ax.invert_yaxis()
    lo, hi = min(v for v in d if v is not None), max(v for v in d if v is not None)
    ax.set_xlim(lo - 8, hi + 8)
    ax.set_xlabel(f"Δ isolated yield vs. C{STANDARD} standard ({std_y:.1f} %) / percentage points")
    ax.grid(axis="x", color="#ddd", lw=0.5, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    # group labels on the right edge, bracketing their rows
    for name, a, b in groups:
        ax.annotate(name, xy=(1.005, (a + b) / 2), xycoords=("axes fraction", "data"),
                    va="center", ha="left", fontsize=7, fontweight="bold", color="#333")
        ax.plot([1.0, 1.0], [a - 0.4, b + 0.4], transform=ax.get_yaxis_transform(),
                color="#999", lw=0.8, clip_on=False)
    fig.text(0.01, 0.01, "† notebook notes an impure product (yield likely overstated). Single runs, no replicates.",
             fontsize=6, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=600)
    fig.savefig(path.with_suffix(".pdf"))
    w_px, h_px = fig.get_size_inches()
    assert h_px <= w_px * 2 / 3
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=RUN / "assembled")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    recs = load(args.input)
    assert set(recs) == set(RUNS), f"missing records: {set(RUNS) - set(recs)}"
    rows, std_y, std = analyse(recs)
    args.output.mkdir(parents=True, exist_ok=True)
    cols = [k for k in rows[0] if not k.startswith("_")]
    with open(args.output / "parameter_sweep.csv", "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, cols, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    (args.output / "standard_features.json").write_text(json.dumps(
        {"run": f"C{STANDARD}", "isolated_yield_percent": std_y, **features(std)}, indent=2, ensure_ascii=False))
    plot(rows, std_y, args.output / "parameter_sweep.png")
    for row in rows:
        print(f"{row['run']:5} {row['category']:20} {row['changed_parameter']:40} {row['delta_yield_pp']!s:>7}  | {row['all_differences']} {row['data_issue']}")


if __name__ == "__main__":
    main()
