#!/usr/bin/env python3
"""Multi-step synthesis routes reconstructed from reagent journal references.

A starting material named e.g. 'Aminoester 065' or 'Ns-Ile-OMe 045c' is linked
to experiment WAT-Ch-065 / WAT-Ch-045 when that record exists in the input
folder. Overall yield = product of the selected step yields along a chain
(documented steps only; precursors without a record contribute nothing).

Dependencies: Python 3.10+, matplotlib. Self-contained, no project imports.

Rerun:
    python3 generated_analyses/multi_step_sequences_1/multi_step_sequences.py \
        --input cases/excel_workbooks/output/run_2026_09_25_10_47/assembled \
        --output generated_analyses/multi_step_sequences_1/outputs

Assumptions:
* Yield selection: C045 'sauber', C063 'Säule 2 (sauber)', C088 'tert. Amin
  a+b' (fixed by the task); otherwise the main product with a recorded yield.
* A link is *uncertain* when the reference carries a sub-batch letter
  (045c, 088b) that the source record does not define, or when the consumed
  mass exceeds the selected product mass.
* A yield is flagged *carry-forward* only if it equals the theoretical mass
  (product mmol == limiting-reagent mmol) AND the records say so in text:
  product named 'quant', reaction 'ohne Aufarbeitung', or the consuming
  record uses the material 'crude'/'Roh'.
* Experiments without any resolved link are isolated and omitted from the
  diagram and statistics. Sibling experiments of the same stage from one
  parent (n >= 2) are grouped and summarised (mean, sample SD, range).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import unicodedata
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import FancyBboxPatch, Patch
from matplotlib.lines import Line2D

SELECT = {
    "WAT-Ch-045": "sauber",
    "WAT-Ch-063": "Säule 2 (sauber)",
    "WAT-Ch-088": "tert. Amin a+b",
}
# (keyword in reaction_name, column label); order = column order
STAGES = [
    ("Methylester", "Methyl\nester"),
    ("oNs-Schützung", "oNs\nprotection"),
    ("Aminierung", "N-alkyl-\nation"),
    ("Reduktion", "LAH\nreduction"),
    ("DMP-Oxidation", "DMP\noxidation"),
    ("Cyclisierung", "Cycli-\nsation"),
    ("Fluorierung", "Hydro-\nfluorination"),
]
REF = re.compile(r"(?<![\d.])(\d{3})([a-z]?)(?![\d.])")
CF_TEXT = re.compile(r"quant|ohne Aufarbeitung", re.I)
CRUDE = re.compile(r"crude|\bRoh\b", re.I)

# Reference sequential ramp (blue 100 -> 700), 0-100 % yield.
CMAP = LinearSegmentedColormap.from_list(
    "yield", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
NORM = Normalize(0, 100)
INK, MUTED, MISSING = "#0b0b0b", "#52514e", "#d9d8d4"


def short(jn: str) -> str:
    return "C" + jn.split("-")[-1]


def stage_of(name: str) -> int | None:
    return next((i for i, (k, _) in enumerate(STAGES) if k in name), None)


def load(input_dir: Path) -> dict[str, dict]:
    docs = {}
    for p in sorted(input_dir.glob("WAT-Ch-*.json")):
        # Some records store umlauts decomposed (NFD); normalise for matching.
        d = json.loads(unicodedata.normalize("NFC", p.read_text(encoding="utf-8")))
        docs[d["journal_number"]] = d
    return docs


def limiting(d: dict) -> dict | None:
    return next((s for s in d["starting_materials"]
                 if s.get("role") == "limiting_reagent"), None)


def select_product(d: dict) -> dict | None:
    prods = d.get("products") or []
    if d["journal_number"] in SELECT:
        return next(p for p in prods if p["name"] == SELECT[d["journal_number"]])
    with_y = [p for p in prods if p.get("yield_percent") is not None]
    return next((p for p in with_y if p.get("is_main_product")),
                with_y[0] if with_y else None)


def build(docs: dict[str, dict]):
    nodes, edges, unresolved = {}, [], []
    for jn, d in docs.items():
        prod = select_product(d)
        nodes[jn] = {
            "id": jn, "label": short(jn), "date": d.get("date"),
            "reaction_name": d["reaction_name"],
            "stage": stage_of(d["reaction_name"]),
            "selected_product": prod["name"] if prod else None,
            "yield_percent": prod.get("yield_percent") if prod else None,
            "yield_g": prod.get("yield_g") if prod else None,
            "carry_forward": False, "carry_forward_evidence": [],
        }
        for sm in d["starting_materials"]:
            if sm.get("role") == "solvent":
                continue
            for num, letter in REF.findall(sm["name"]):
                src = f"WAT-Ch-{num}"
                if src == jn:
                    continue
                if src not in docs:
                    unresolved.append({"experiment": jn, "reagent": sm["name"],
                                       "referenced": src, "role": sm.get("role")})
                    continue
                edges.append({"source": src, "target": jn, "reagent": sm["name"],
                              "suffix": letter, "role": sm.get("role"),
                              "consumed_g": sm.get("mass_g"),
                              "consumed_mmol": sm.get("amount_mmol")})
    for e in edges:
        src = docs[e["source"]]
        sel = nodes[e["source"]]["yield_g"]
        fr = [(p["name"], p["yield_g"]) for p in src["products"] if p.get("yield_g")]
        why = []
        if e["suffix"]:
            why.append(f"sub-batch '{e['suffix']}' not defined in {short(e['source'])}")
        if e["consumed_g"] and fr:
            name, g = min(fr, key=lambda t: abs(t[1] - e["consumed_g"]))
            e["closest_fraction"] = name
            e["closest_fraction_g"] = round(g, 4)
            if sel and e["consumed_g"] > 1.02 * sel:
                why.append("consumed mass exceeds selected product mass")
            if (name != nodes[e["source"]]["selected_product"]
                    and abs(g - e["consumed_g"]) / g < 0.005):
                why.append(f"consumed mass matches fraction '{name}' "
                           f"({g:.3f} g), not the selected one")
        e["uncertain"] = bool(why)
        e["uncertain_reason"] = why
    # Carry-forward: theoretical mass + textual record evidence.
    for jn, n in nodes.items():
        prod = select_product(docs[jn])
        lim = limiting(docs[jn])
        if not prod or not lim or not prod.get("amount_mmol") or not lim.get("amount_mmol"):
            continue
        if abs(prod["amount_mmol"] / lim["amount_mmol"] - 1) > 1e-3:
            continue
        ev = []
        if CF_TEXT.search(prod["name"]):
            ev.append(f"product labelled '{prod['name']}'")
        if CF_TEXT.search(docs[jn]["reaction_name"]):
            ev.append(f"reaction '{docs[jn]['reaction_name']}'")
        for e in edges:
            if e["source"] == jn:
                t = docs[e["target"]]
                if CRUDE.search(e["reagent"]) or CRUDE.search(t["reaction_name"]):
                    ev.append(f"used crude in {short(e['target'])}")
        n["theoretical_mass"] = True
        if ev:
            n["carry_forward"], n["carry_forward_evidence"] = True, ev
    linked = {e["source"] for e in edges} | {e["target"] for e in edges}
    for jn, n in nodes.items():
        n["isolated"] = jn not in linked
    return nodes, edges, unresolved


def chains(nodes, edges):
    parents = {}
    for e in edges:
        parents.setdefault(e["target"], []).append(e)
    children = {}
    for e in edges:
        children.setdefault(e["source"], []).append(e["target"])
    leaves = [j for j in nodes if j in parents and j not in children]
    out = []
    for leaf in sorted(leaves):
        path, links, cur = [leaf], [], leaf
        while cur in parents:
            e = parents[cur][0]  # ponytail: one parent per experiment here; branch merge if converging routes appear
            links.insert(0, e)
            cur = e["source"]
            path.insert(0, cur)
        ys = [nodes[j]["yield_percent"] for j in path]
        doc = [y for y in ys if y is not None]
        overall = 100.0
        for y in doc:
            overall *= y / 100
        out.append({
            "leaf": leaf, "root": path[0], "path": path,
            "n_steps": len(path), "n_steps_with_yield": len(doc),
            "overall_yield_percent": overall if doc else None,
            "partial": len(doc) < len(path),
            "uncertain_links": [f"{short(e['source'])}->{short(e['target'])}"
                                for e in links if e["uncertain"]],
            "carry_forward_steps": [short(j) for j in path if nodes[j]["carry_forward"]],
        })
    return out, children


def compact(labels: list[str]) -> str:
    """['C113', 'C114', 'C115', 'C134'] -> 'C113–115, 134' (consecutive runs)."""
    nums = [int(lab[1:]) for lab in labels]
    runs, start = [], nums[0]
    for a, b in zip(nums, nums[1:] + [None]):
        if b != a + 1:
            runs.append(f"{start:03d}" if start == a else f"{start:03d}–{a:03d}")
            start = b
    return "C" + ",\n".join(runs)


def summary(vals):
    return {"n": len(vals), "mean": statistics.fmean(vals),
            "sd": statistics.stdev(vals) if len(vals) > 1 else None,
            "min": min(vals), "max": max(vals)}


def draw(nodes, edges, chain_rows, children, unresolved, out: Path):
    # Group same-stage siblings (n >= 2) under their parent.
    groups = {}
    for p, kids in children.items():
        by_stage = {}
        for k in kids:
            by_stage.setdefault(nodes[k]["stage"], []).append(k)
        for st, ks in by_stage.items():
            if len(ks) >= 2:
                groups[p] = sorted(ks)
    grouped = {k for ks in groups.values() for k in ks}
    spines = {}
    for c in chain_rows:
        if c["leaf"] in grouped:
            spines.setdefault(c["root"], c["path"][:-1])
        else:
            spines[c["root"]] = c["path"]
    roots = sorted(spines, key=lambda r: nodes[r]["date"])
    by_leaf = {c["leaf"]: c for c in chain_rows}

    W, H, DY = 0.78, 0.50, 0.78
    fig, ax = plt.subplots(figsize=(7.0, 0.55 + DY * len(roots) + 0.35))
    ax.set_xlim(-0.45, len(STAGES) + 0.85)
    ax.set_ylim(-DY * (len(roots) - 1) - 0.50, 0.72)
    ax.axis("off")
    for i, (_, lab) in enumerate(STAGES):
        ax.text(i, 0.5, lab, ha="center", va="center", fontsize=6.5, color=MUTED)
    ax.text(len(STAGES) + 0.25, 0.5, "Overall\n(documented)", ha="center",
            va="center", fontsize=6.5, color=MUTED)

    def box(x, y, lines, yv, cf=False, h=H, w=W):
        fc = MISSING if yv is None else CMAP(NORM(yv))
        ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                    boxstyle="round,pad=0,rounding_size=0.06",
                                    fc=fc, ec="white" if not cf else INK,
                                    lw=0.6, hatch="////" if cf else None))
        tc = "white" if yv is not None and yv > 55 else INK
        ax.text(x, y, "\n".join(lines), ha="center", va="center", fontsize=6.6,
                color=tc, linespacing=1.15,
                bbox=dict(fc=fc, ec="none", pad=0.4) if cf else None)

    def arrow(x0, x1, y, e):
        ax.annotate("", (x1 - W / 2, y), (x0 + W / 2, y),
                    arrowprops=dict(arrowstyle="-|>", lw=0.8, color=INK,
                                    ls=(0, (2, 1.5)) if e["uncertain"] else "-",
                                    shrinkA=0, shrinkB=0, mutation_scale=7))
        if e["uncertain"]:
            ax.text((x0 + x1) / 2, y + H / 2 + 0.02, e["reagent"].split()[-1] + "?",
                    ha="center", va="bottom", fontsize=5.2, color=MUTED)

    emap = {(e["source"], e["target"]): e for e in edges}
    used_flags = set()
    for r, root in enumerate(roots):
        y = -r * DY
        path = spines[root]
        for j in path:
            n = nodes[j]
            yv = n["yield_percent"]
            ytxt = "n.d." if yv is None else f"{yv:.0f} %" + ("†" if n["carry_forward"] else "")
            box(n["stage"], y, [r"$\bf{" + n["label"] + "}$", ytxt], yv, n["carry_forward"])
            used_flags.add("cf" if n["carry_forward"] else "")
            used_flags.add("missing" if yv is None else "")
            note = [u for u in unresolved if u["experiment"] == j]
            if note:
                ax.text(n["stage"], y - H / 2 - 0.03,
                        "+ " + ", ".join("C" + u["referenced"][-3:] for u in note) + "*",
                        ha="center", va="top", fontsize=5.5, color=MUTED, style="italic")
                used_flags.add("unresolved")
            if "Cyclisierung" in n["reaction_name"]:
                reag = [s["name"].split()[0] for s in [*_doc_cache[j]["starting_materials"]]
                        if s.get("role") in ("reductant", "catalyst")]
                ax.text(n["stage"], y + H / 2 + 0.02, "/".join(reag), ha="center",
                        va="bottom", fontsize=5.5, color=MUTED)
        for a, b in zip(path, path[1:]):
            e = emap[(a, b)]
            arrow(nodes[a]["stage"], nodes[b]["stage"], y, e)
            used_flags.add("uncertain" if e["uncertain"] else "")
        last = path[-1]
        x_last = nodes[last]["stage"]
        txt_lines = []
        if last in groups:
            ks = groups[last]
            s = summary([nodes[k]["yield_percent"] for k in ks if nodes[k]["yield_percent"] is not None])
            ov = summary([by_leaf[k]["overall_yield_percent"] for k in ks])
            gx = nodes[ks[0]]["stage"]
            box(gx, y, [compact([nodes[k]["label"] for k in ks]),
                        f"n = {s['n']}", f"{s['mean']:.0f} ± {s['sd']:.0f} %",
                        f"({s['min']:.0f}–{s['max']:.0f})"], s["mean"], h=H * 1.75)
            ax.annotate("", (gx - W / 2, y), (x_last + W / 2, y),
                        arrowprops=dict(arrowstyle="-|>", lw=0.8, color=INK, shrinkA=0,
                                        shrinkB=0, mutation_scale=7))
            ax.text((x_last + gx) / 2, y + 0.06, "×" + str(s["n"]), ha="center",
                    va="bottom", fontsize=5.5, color=MUTED)
            spine_ov = next(c for c in chain_rows if c["leaf"] in ks)["overall_yield_percent"] \
                / (nodes[ks[0]]["yield_percent"] / 100)
            txt_lines = [f"{nodes[last]['label']}: {spine_ov:.1f} %",
                         f"fluorides: {ov['mean']:.1f} ± {ov['sd']:.1f} %",
                         f"({ov['min']:.1f}–{ov['max']:.1f})"]
            x_last = gx
        else:
            c = by_leaf[last]
            txt_lines = [f"{nodes[last]['label']}: {c['overall_yield_percent']:.1f} %"
                         + (" (partial)" if c["partial"] else "")]
        ax.text(len(STAGES) + 0.25 if last in groups else x_last + W / 2 + 0.12, y,
                "\n".join(txt_lines), ha="center" if last in groups else "left",
                va="center", fontsize=6.6, color=INK, linespacing=1.2)

    # Legend + colour bar.
    handles = []
    if "uncertain" in used_flags:
        handles.append(Line2D([], [], color=INK, lw=0.8, ls=(0, (2, 1.5)), label="uncertain link"))
    if "cf" in used_flags:
        handles.append(Patch(fc="white", ec=INK, hatch="////", lw=0.6,
                             label="† carry-forward (100 % assumed, record evidence)"))
    if "missing" in used_flags:
        handles.append(Patch(fc=MISSING, ec="none", label="yield missing (n.d.)"))
    if "unresolved" in used_flags:
        handles.append(Line2D([], [], color="none",
                              label="+C0xx* co-reactant without record"))
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.005, 0.01),
               ncol=len(handles), fontsize=5.8, frameon=False, handlelength=1.8,
               columnspacing=1.0, borderaxespad=0)
    cax = fig.add_axes([0.80, 0.035, 0.17, 0.02])
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=NORM, cmap=CMAP), cax=cax,
                      orientation="horizontal", ticks=[0, 50, 100])
    cb.ax.tick_params(labelsize=5.5, length=1.5, pad=1)
    cb.outline.set_visible(False)
    cb.set_label("step yield / %", fontsize=5.8, labelpad=1)
    cb.ax.xaxis.set_label_position("top")
    fig.subplots_adjust(0.005, 0.11, 0.995, 0.995)
    for ext in ("png", "pdf"):
        fig.savefig(out / f"multi_step_routes.{ext}", dpi=600 if ext == "png" else None)
    plt.close(fig)
    return groups


_doc_cache: dict[str, dict] = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    docs = load(a.input)
    _doc_cache.update(docs)
    nodes, edges, unresolved = build(docs)
    chain_rows, children = chains(nodes, edges)

    # Self-checks against the source records.
    c068 = next(c for c in chain_rows if c["leaf"] == "WAT-Ch-068")
    exp = 1.0
    for j in c068["path"]:
        exp *= nodes[j]["yield_percent"] / 100
    assert abs(c068["overall_yield_percent"] - 100 * exp) < 1e-9
    assert abs(nodes["WAT-Ch-063"]["yield_percent"] - 29.43) < 0.01
    assert all(nodes[j]["stage"] is not None for j in nodes if not nodes[j]["isolated"])
    e65 = next(e for e in edges if e["target"] == "WAT-Ch-065")
    assert compact(["C113", "C114", "C115", "C134"]) == "C113–115,\n134"
    assert e65["closest_fraction"] == "Säule 2 (sauber)" and not e65["uncertain"]

    groups = draw(nodes, edges, chain_rows, children, unresolved, a.output)

    linked = {j: n for j, n in nodes.items() if not n["isolated"]}
    (a.output / "dependency_graph.json").write_text(json.dumps({
        "nodes": list(linked.values()), "edges": edges,
        "unresolved_references": unresolved,
        "isolated_omitted": sorted(short(j) for j, n in nodes.items() if n["isolated"]),
        "groups": {short(p): [short(k) for k in ks] for p, ks in groups.items()},
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    with open(a.output / "chain_yields.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["leaf", "route", "n_steps", "n_steps_with_yield",
                    "overall_yield_percent", "partial", "uncertain_links",
                    "carry_forward_steps", "grouped_branch_of"])
        gof = {k: short(p) for p, ks in groups.items() for k in ks}
        for c in chain_rows:
            w.writerow([short(c["leaf"]), " > ".join(short(j) for j in c["path"]),
                        c["n_steps"], c["n_steps_with_yield"],
                        f"{c['overall_yield_percent']:.3f}", c["partial"],
                        ";".join(c["uncertain_links"]), ";".join(c["carry_forward_steps"]),
                        gof.get(c["leaf"], "")])

    with open(a.output / "step_yields.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["experiment", "date", "stage", "reaction_name", "selected_product",
                    "yield_g", "yield_percent", "carry_forward", "carry_forward_evidence",
                    "theoretical_mass", "precursors", "all_products"])
        for j, n in sorted(linked.items()):
            w.writerow([n["label"], n["date"], STAGES[n["stage"]][1].replace("-\n", "").replace("\n", " "),
                        n["reaction_name"], n["selected_product"],
                        "" if n["yield_g"] is None else f"{n['yield_g']:.4f}",
                        "" if n["yield_percent"] is None else f"{n['yield_percent']:.2f}",
                        n["carry_forward"], "; ".join(n["carry_forward_evidence"]),
                        n.get("theoretical_mass", False),
                        "; ".join(f"{e['reagent']}" for e in edges if e["target"] == j)
                        + "".join(f"; {u['reagent']} (no record)" for u in unresolved if u["experiment"] == j),
                        "; ".join(f"{p['name']}={p.get('yield_percent') and round(p['yield_percent'], 2)}"
                                  for p in docs[j]["products"])])

    # Stage statistics: one yield per connected experiment, before grouping.
    with open(a.output / "stage_statistics.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["stage", "n", "mean_percent", "sd_percent", "min_percent",
                    "max_percent", "experiments"])
        for i, (_, lab) in enumerate(STAGES):
            ex = sorted(j for j, n in linked.items() if n["stage"] == i and n["yield_percent"] is not None)
            if not ex:
                continue
            s = summary([nodes[j]["yield_percent"] for j in ex])
            w.writerow([lab.replace("-\n", "").replace("\n", " "), s["n"], f"{s['mean']:.2f}",
                        "" if s["sd"] is None else f"{s['sd']:.2f}",
                        f"{s['min']:.2f}", f"{s['max']:.2f}", " ".join(short(j) for j in ex)])

    for c in chain_rows:
        if c["leaf"] not in {k for ks in groups.values() for k in ks}:
            print(f"{short(c['leaf'])}: {c['overall_yield_percent']:.2f} %  "
                  f"uncertain={c['uncertain_links']} cf={c['carry_forward_steps']}")
    for p, ks in groups.items():
        print(f"group from {short(p)}: n={len(ks)}")
    print("isolated:", sorted(short(j) for j, n in nodes.items() if n["isolated"]))
    print("unresolved:", [(short(u['experiment']), u['reagent']) for u in unresolved])


if __name__ == "__main__":
    main()
