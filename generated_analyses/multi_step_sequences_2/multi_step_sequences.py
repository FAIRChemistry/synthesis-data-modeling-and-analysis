#!/usr/bin/env python3
"""Multi-step synthesis routes reconstructed from reagent journal references.

A starting material named e.g. 'Aminoester 065' or 'Ns-Ile-OMe 045c' is linked
to experiment WAT-Ch-065 / WAT-Ch-045 when that record exists in the input
folder. Overall yield = product of the selected step yields along a chain
(documented steps only; precursors without a record contribute nothing).

Attempt 2: identical route/yield analysis to attempt 1; the experiment boxes
are replaced by RDKit drawings of each experiment's *selected* product.

Dependencies: Python 3.10+, matplotlib, rdkit, olefile, openpyxl, Open Babel
(`obabel` on PATH). Uses src/preprocess.py for the CDX extraction.

Rerun:
    python3 generated_analyses/multi_step_sequences_2/multi_step_sequences.py \
        --input cases/excel_workbooks/output/run_2026_09_25_10_47/assembled \
        --output generated_analyses/multi_step_sequences_2/outputs
(workbooks default to <input>/../inputs/input/workbooks; override --workbooks)

Structures (selected product per experiment):
* Source = the native ChemDraw (CDX) scheme embedded in each workbook, read via
  preprocess._cdx_payloads / extract_embedded_chemical_structures (Open Babel).
* Open Babel turns some contracted ChemDraw labels into '*'. Such a '*' is
  resolved only when the drawing contains exactly one known label whose
  embedded ChemDraw fragment has the expected atoms (LABELS below), and the
  '*' is a terminal substituent. Everything else is reported as unresolved.
* A scheme can draw several products (C083, C091: olefin + tertiary alcohol).
  The selected product's structure is the drawn product whose RDKit molar mass
  matches the selected table row's molar_mass_g_mol (|Δ| < 0.05 g/mol); other
  drawn products are reported as side products (matching another row) or as
  drawn without a table row. No name lookup is used.

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
import io
import statistics
import struct
import sys
import unicodedata
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import Circle, Patch
from matplotlib.lines import Line2D
from rdkit import Chem, RDLogger
from rdkit.Chem import Descriptors, rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
import preprocess  # noqa: E402  (CDX extraction lives here)

RDLogger.DisableLog("rdApp.*")
rdDepictor.SetPreferCoordGen(True)

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


# ---------------------------------------------------------------- structures
# Contracted ChemDraw label -> (substituent replacing a terminal '*', counter-
# ion appended as a separate component, atom texts of the label's embedded
# ChemDraw fragment that must be present for the resolution to be accepted).
LABELS = {
    "O2N": ("[N+](=O)[O-]", "", {"N+", "O", "O-"}),
    "NH3Cl": ("[NH3+]", ".[Cl-]", {"NH3", "Cl"}),
}
MW_TOL = 0.05


def cdx_labels(payload: bytes) -> dict[str, set[str]]:
    """Contracted node labels in a CDX stream -> atom texts of their fragment.

    CDX = 22-byte header, then objects (tag >= 0x8000, 4-byte id, properties,
    0x0000 terminator) and properties (tag, 2-byte length, data). A label node
    (0x8004) owns a Text object (0x8006) and, if contracted, a nested fragment
    (0x8003) whose nodes carry their own texts. Text property = 0x0700.
    """
    i, stack, own, inner = 22, [], {}, {}
    while i + 2 <= len(payload):
        tag, = struct.unpack_from("<H", payload, i)
        i += 2
        if tag == 0:
            if not stack:
                break
            stack.pop()
            continue
        if tag & 0x8000:
            stack.append((tag, struct.unpack_from("<I", payload, i)[0]))
            i += 4
            continue
        n, = struct.unpack_from("<H", payload, i)
        i += 2
        if n == 0xFFFF:
            n, = struct.unpack_from("<I", payload, i)
            i += 4
        data, i = payload[i:i + n], i + n
        if tag != 0x0700 or len(stack) < 2 or stack[-1][0] != 0x8006 or stack[-2][0] != 0x8004:
            continue
        runs, = struct.unpack_from("<H", data, 0)
        text = data[2 + 10 * runs:].decode("latin-1")
        own[stack[-2][1]] = text
        if len(stack) >= 4 and stack[-3][0] == 0x8003 and stack[-4][0] == 0x8004:
            inner.setdefault(stack[-4][1], set()).add(text)
    out: dict[str, set[str]] = {}
    for node, text in own.items():
        if node in inner:
            out.setdefault(text, set()).update(inner[node])
    return out


def resolve_star(smi: str, labels: dict[str, set[str]]) -> tuple[str | None, str]:
    """Replace one terminal '*' using the drawing's only known label."""
    known = [lab for lab in labels if lab in LABELS]
    if smi.count("*") != 1:
        return None, f"{smi.count('*')} attachment points"
    if len(known) != 1:
        return None, f"labels in drawing: {sorted(labels)}; none/several resolvable"
    lab = known[0]
    sub, counter, atoms = LABELS[lab]
    if not atoms <= labels[lab]:
        return None, f"label {lab} fragment atoms {sorted(labels[lab])} != expected {sorted(atoms)}"
    if "(*)" not in smi and not smi.endswith("*"):
        return None, "'*' is not a terminal substituent"
    return smi.replace("*", sub) + counter, f"label '{lab}' resolved from embedded CDX fragment"


def mol_info(smi: str) -> dict:
    m = Chem.MolFromSmiles(smi)
    return {"smiles": Chem.MolToSmiles(m), "inchi": Chem.MolToInchi(m),
            "inchikey": Chem.MolToInchiKey(m), "mw": Descriptors.MolWt(m)}


def structures(docs: dict[str, dict], jns, wb_dir: Path, select) -> list[dict]:
    """One row per drawn product per experiment, role-tagged."""
    rows = []
    for jn in jns:
        d, sel = docs[jn], select(docs[jn])
        wb = next(wb_dir.glob(f"{jn} *.xlsx"))
        payloads = preprocess._cdx_payloads(wb)
        labels: dict[str, set[str]] = {}
        for p in payloads:
            for k, v in cdx_labels(p).items():
                labels.setdefault(k, set()).update(v)
        rxns = [r for r in preprocess.extract_embedded_chemical_structures(wb)["reaction_smiles"]
                if ">" in r]
        drawn = [s for r in rxns for role, s in preprocess._reaction_components(r)
                 if role == "product"]
        base = {"experiment": short(jn), "n_cdx_schemes": len(payloads),
                "selected_row": sel["name"] if sel else None,
                "selected_row_mw": sel.get("molar_mass_g_mol") if sel else None}
        if not drawn:
            rows.append({**base, "role": "unresolved", "note": "no product in CDX scheme"})
        for raw in drawn:
            smi, note = raw, "complete in CDX"
            if "*" in raw:
                smi, note = resolve_star(raw, labels)
            r = {**base, "cdx_smiles": raw, "note": note}
            if smi is None:
                rows.append({**r, "role": "unresolved"})
                continue
            info = mol_info(smi)
            r.update(info)
            match = [p for p in d["products"] if p.get("molar_mass_g_mol")
                     and abs(p["molar_mass_g_mol"] - info["mw"]) < MW_TOL]
            if sel and sel in match:
                r["role"] = "selected"
            elif match:
                r["role"] = "side product: " + ", ".join(p["name"] for p in match)
            else:
                r["role"] = "drawn, no matching table row"
            if sel and sel.get("inchikey"):
                r["json_inchikey_agrees"] = sel["inchikey"] == info["inchikey"]
            rows.append(r)
        if sum(r["role"] == "selected" for r in rows if r["experiment"] == short(jn)) != 1:
            for r in rows:
                if r["experiment"] == short(jn) and r["role"] == "selected":
                    r["role"] = "unresolved"
                    r["note"] += "; several drawn products match the selected molar mass"
    return rows


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


# Molecule drawing scale: one bond = BOND_IN inches for every structure.
BOND_IN, IMG_DPI = 0.082, 600
# Common core of the open-chain N-alkyl intermediates (ester/alcohol/aldehyde):
# depicted once and reused so the three columns share one orientation.
CORE = Chem.MolFromSmiles("CC[C@H](C)[C@@H](C)N(CCC=C(C)C)S(=O)(=O)c1ccccc1[N+](=O)[O-]")
rdDepictor.Compute2DCoords(CORE)


def mol_image(smi: str):
    """Transparent, tightly cropped RGBA depiction + its size in inches."""
    m = Chem.MolFromSmiles(smi)
    rdDepictor.Compute2DCoords(m)
    if m.HasSubstructMatch(CORE):
        rdDepictor.GenerateDepictionMatching2DStructure(m, CORE)
    d = rdMolDraw2D.MolDraw2DCairo(2400, 2400)
    o = d.drawOptions()
    o.fixedBondLength = BOND_IN * IMG_DPI
    o.useBWAtomPalette()
    o.setBackgroundColour((1, 1, 1, 0))
    o.clearBackground = False
    o.bondLineWidth = 4  # px at IMG_DPI ~ 0.5 pt
    o.baseFontSize = 0.8
    o.padding = 0.0
    d.DrawMolecule(m)
    d.FinishDrawing()
    img = plt.imread(io.BytesIO(d.GetDrawingText()), format="png")
    ys, xs = np.nonzero(img[..., 3] > 0)
    img = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return img, img.shape[1] / IMG_DPI, img.shape[0] / IMG_DPI


def subscript(s: str) -> str:
    return re.sub(r"\d", lambda m: chr(0x2080 + int(m.group())), s)


def draw(nodes, edges, chain_rows, children, unresolved, out: Path):
    # Group same-stage siblings (n >= 2) under their parent (as attempt 1).
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

    imgs = {j: mol_image(n["product_smiles"]) for j, n in nodes.items()
            if n.get("product_smiles") and not n["isolated"]}
    for p, ks in groups.items():
        keys = {nodes[k].get("product_inchikey") for k in ks}
        assert len(keys) == 1 and None not in keys, f"group {short(p)} products differ: {keys}"

    # Layout in inches (axes data units == inches, so depictions are undistorted).
    FW, X0, PITCH, GAP = 7.0, 0.40, 0.865, 0.035
    TOP, LEG = 0.30, 0.34
    row_h = []
    for root in roots:
        js = spines[root] + groups.get(spines[root][-1], [])[:1]
        row_h.append(max(imgs[j][2] for j in js if j in imgs))
    ROW_PAD = 0.36  # id above + yield/notes below
    FH = TOP + sum(h + ROW_PAD for h in row_h) + LEG
    fig = plt.figure(figsize=(FW, FH))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, FW)
    ax.set_ylim(0, FH)
    ax.axis("off")
    X = lambda st: X0 + st * PITCH  # noqa: E731
    X_OV = X(len(STAGES) - 1) + PITCH * 0.5 + 0.42
    for i, (_, lab) in enumerate(STAGES):
        ax.text(X(i), FH - 0.03, lab, ha="center", va="top", fontsize=6.5, color=MUTED,
                linespacing=1.05)
    ax.text(X_OV, FH - 0.03, "Overall\n(documented)", ha="center", va="top",
            fontsize=6.5, color=MUTED, linespacing=1.05)

    used = set()

    def yield_label(x, y, yv, txt, cf=False):
        """Coloured disc (yield colour; hatched = carry-forward) + yield text."""
        fc = MISSING if yv is None else CMAP(NORM(yv))
        r = 0.032
        ax.add_patch(Circle((x - 0.075, y - r - 0.005), r, fc=fc,
                            ec=INK if cf else "none", lw=0.4, hatch="//////" if cf else None))
        ax.text(x - 0.03, y, txt, ha="left", va="top", fontsize=6.4, color=INK)
        used.add("cf" if cf else "")
        used.add("missing" if yv is None else "")

    def molecule(j, x, y, half_h, idtxt):
        if j in imgs:
            img, w, h = imgs[j]
            ax.imshow(img, extent=(x - w / 2, x + w / 2, y - h / 2, y + h / 2),
                      interpolation="lanczos", aspect="auto", zorder=2)
        else:
            w = 0.5
            ax.text(x, y, "structure\nunresolved", ha="center", va="center",
                    fontsize=5.5, color=MUTED, style="italic")
            used.add("unres_struct")
        ax.text(x, y + half_h + 0.025, idtxt, ha="center", va="bottom", fontsize=5.6,
                color=MUTED, fontweight="bold")
        return w

    def arrow(xa, xb, y, uncertain=False, label=None):
        ax.annotate("", (xb, y), (xa, y),
                    arrowprops=dict(arrowstyle="-|>", lw=0.7, color=INK,
                                    ls=(0, (2, 1.5)) if uncertain else "-",
                                    shrinkA=0, shrinkB=0, mutation_scale=6))
        if label:
            ax.text((xa + xb) / 2, y + 0.03, label, ha="center", va="bottom",
                    fontsize=5.0, color=MUTED)

    emap = {(e["source"], e["target"]): e for e in edges}
    ytop = FH - TOP
    for r, root in enumerate(roots):
        hh = row_h[r] / 2
        y = ytop - 0.11 - hh
        ytop -= row_h[r] + ROW_PAD
        path = spines[root]
        widths = {}
        for j in path:
            n = nodes[j]
            x = X(n["stage"])
            widths[j] = molecule(j, x, y, hh, n["label"])
            yv = n["yield_percent"]
            ytxt = "n.d." if yv is None else f"{yv:.0f} %" + ("†" if n["carry_forward"] else "")
            yield_label(x, y - hh - 0.025, yv, ytxt, n["carry_forward"])
            note = [u for u in unresolved if u["experiment"] == j]
            if note:
                ax.text(x, y - hh - 0.135,
                        "+ " + ", ".join("C" + u["referenced"][-3:] for u in note) + "*",
                        ha="center", va="top", fontsize=5.3, color=MUTED, style="italic")
                used.add("unresolved")
        for a, b in zip(path, path[1:]):
            e = emap[(a, b)]
            lab = e["reagent"].split()[-1] + "?" if e["uncertain"] else None
            if "Cyclisierung" in nodes[b]["reaction_name"]:
                lab = subscript("/".join(s["name"].split()[0]
                                         for s in _doc_cache[b]["starting_materials"]
                                         if s.get("role") in ("reductant", "catalyst")))
            arrow(X(nodes[a]["stage"]) + widths[a] / 2 + GAP,
                  X(nodes[b]["stage"]) - widths[b] / 2 - GAP, y, e["uncertain"], lab)
            used.add("uncertain" if e["uncertain"] else "")
        last = path[-1]
        x_last = X(nodes[last]["stage"])
        if last in groups:
            ks = groups[last]
            s = summary([nodes[k]["yield_percent"] for k in ks if nodes[k]["yield_percent"] is not None])
            ov = summary([by_leaf[k]["overall_yield_percent"] for k in ks])
            gx = X(nodes[ks[0]]["stage"])
            ids = compact([nodes[k]["label"] for k in ks]).replace(",\n", ", ")
            gw = molecule(ks[0], gx, y, hh, ids)
            yield_label(gx, y - hh - 0.025, s["mean"], f"{s['mean']:.0f} ± {s['sd']:.0f} %")
            ax.text(gx, y - hh - 0.135, f"n = {s['n']}, range {s['min']:.0f}–{s['max']:.0f} %",
                    ha="center", va="top", fontsize=5.3, color=MUTED)
            arrow(x_last + widths[last] / 2 + GAP, gx - gw / 2 - GAP, y, label="×" + str(s["n"]))
            spine_ov = next(c for c in chain_rows if c["leaf"] in ks)["overall_yield_percent"] \
                / (nodes[ks[0]]["yield_percent"] / 100)
            ax.text(X_OV, y, f"{nodes[last]['label']}: {spine_ov:.1f} %\n"
                    f"fluorides:\n{ov['mean']:.1f} ± {ov['sd']:.1f} %\n"
                    f"({ov['min']:.1f}–{ov['max']:.1f})",
                    ha="center", va="center", fontsize=6.4, color=INK, linespacing=1.2)
        else:
            c = by_leaf[last]
            ax.text(x_last + widths[last] / 2 + 0.12, y,
                    f"{nodes[last]['label']}: {c['overall_yield_percent']:.1f} %"
                    + (" (partial)" if c["partial"] else ""),
                    ha="left", va="center", fontsize=6.4, color=INK)

    # Legend + colour bar.
    from matplotlib.legend_handler import HandlerPatch
    disc = HandlerPatch(patch_func=lambda legend, orig_handle, xdescent, ydescent, width,
                        height, fontsize: Circle((width / 2 - xdescent, height / 2 - ydescent),
                                                 height / 1.6))
    handles = []
    if "uncertain" in used:
        handles.append(Line2D([], [], color=INK, lw=0.7, ls=(0, (2, 1.5)), label="uncertain link"))
    if "cf" in used:
        handles.append(Patch(fc="white", ec=INK, hatch="//////", lw=0.4,
                             label="† carry-forward (100 % assumed, record evidence)"))
    if "missing" in used:
        handles.append(Patch(fc=MISSING, ec="none", label="yield missing (n.d.)"))
    if "unresolved" in used:
        handles.append(Line2D([], [], color="none", label="+C0xx* co-reactant without record"))
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.005, 0.012),
               ncol=len(handles), fontsize=5.8, frameon=False, handlelength=1.6,
               columnspacing=1.0, borderaxespad=0, handler_map={Patch: disc})
    cax = fig.add_axes([0.80, 0.045 * 4.0 / FH, 0.17, 0.08 / FH])
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=NORM, cmap=CMAP), cax=cax,
                      orientation="horizontal", ticks=[0, 50, 100])
    cb.ax.tick_params(labelsize=5.5, length=1.5, pad=1)
    cb.outline.set_visible(False)
    cb.set_label("step yield / %", fontsize=5.8, labelpad=1)
    cb.ax.xaxis.set_label_position("top")
    plt.rcParams["hatch.linewidth"] = 0.4
    for ext in ("png", "pdf"):
        fig.savefig(out / f"multi_step_routes.{ext}", dpi=600 if ext == "png" else None)
    plt.close(fig)
    return groups


_doc_cache: dict[str, dict] = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--workbooks", type=Path, default=None)
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

    # Selected-product structures from the native ChemDraw schemes.
    wb_dir = a.workbooks or a.input.parent / "inputs" / "input" / "workbooks"
    linked_ids = sorted(j for j, n in nodes.items() if not n["isolated"])
    srows = structures(docs, linked_ids, wb_dir, select_product)
    for r in srows:
        if r["role"] == "selected":
            n = nodes["WAT-Ch-" + r["experiment"][1:]]
            n["product_smiles"], n["product_inchikey"] = r["smiles"], r["inchikey"]
    # Label resolution self-checks: a resolved O2N/NH3Cl label must reproduce the
    # tabulated molar mass (role 'selected' already implies it); C083/C091 keep
    # the olefin as selected and the tertiary alcohol as non-selected.
    assert resolve_star("c1c(*)cccc1", {"O2N": {"N+", "O", "O-"}})[0] == "c1c([N+](=O)[O-])cccc1"
    assert resolve_star("C*C", {"O2N": {"N+", "O", "O-"}})[0] is None
    assert resolve_star("C(*)", {"O2N": {"N+", "O"}})[0] is None
    for jn in ("C083", "C091"):
        rs = [r for r in srows if r["experiment"] == jn]
        assert [round(r["mw"], 1) for r in rs if r["role"] == "selected"] == [382.5]
        assert any(round(r["mw"], 1) == 400.5 and r["role"] != "selected" for r in rs)

    with open(a.output / "structures.csv", "w", newline="", encoding="utf-8") as f:
        cols = ["experiment", "role", "selected_row", "selected_row_mw", "mw", "smiles",
                "inchi", "inchikey", "cdx_smiles", "note", "json_inchikey_agrees", "n_cdx_schemes"]
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        for r in srows:
            w.writerow({**r, "mw": f"{r['mw']:.2f}" if "mw" in r else ""})

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
