#!/usr/bin/env python3
"""Synthesis product timeline for the Chemotion ELN records.

One circle per synthesis entry: x = date, y = product substance, area ∝
isolated amount (mmol), label = journal number.  Entries without an amount are
drawn as empty circles.  Products are grouped across names/formulas via a
union of product name, the InChI-derived Hill formula, the InChIKey and the
reaction-name target ("Synthesis of X (remark)" -> X).  Arrows link a product
to a later entry only when its sample label (product `note`, e.g. AD-31)
reappears as the prefix of a starting-material label (AD-31-1).

Requires matplotlib.
    python3 product_timeline.py [--data DIR] [--out DIR]
"""
import argparse, csv, json, math, re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch
from matplotlib.path import Path as MplPath
from matplotlib.text import Text
from matplotlib.transforms import Bbox

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / "cases/chemotion_eln/output/run_2026_07_17_19_26/assembled"

BLUE, INK, MUTED, GRID = "#2a78d6", "#0b0b0b", "#52514e", "#e4e3df"
PT_PER_MMOL = 900          # marker area (pt²) per mmol; 0.04 mmol -> ~6 pt diameter
EMPTY_AREA = 0.10 * PT_PER_MMOL
LEGEND_MMOL = (0.05, 0.2, 0.5)
FORMULA = re.compile(r"^(?:[A-Z][a-z]?\d*)+$")


def hill(inchi):
    """Hill formula from the InChI formula layer, e.g. 'C120H88N8.Co' -> 'C120H88CoN8'."""
    if not inchi:
        return None
    n = Counter()
    for part in inchi.split("/")[1].split("."):
        mult, part = re.match(r"(\d*)(.*)", part).groups()
        for el, k in re.findall(r"([A-Z][a-z]?)(\d*)", part):
            n[el] += int(k or 1) * int(mult or 1)
    order = [e for e in ("C", "H") if e in n] + sorted(e for e in n if e not in ("C", "H"))
    return "".join(e + (str(n[e]) if n[e] > 1 else "") for e in order)


def target(reaction_name):
    """'Synthesis of X (scale-up) ' -> 'X'; keeps parentheses that belong to X."""
    name = re.sub(r"^Synthesis of\s+", "", reaction_name.strip())
    return re.sub(r"\s+\([^()]*\)$", "", name).strip()


def pretty(name):
    return name.replace(")2", ")₂")


def load(data_dir):
    rows = []
    for f in sorted(Path(data_dir).glob("*.json")):
        r = json.loads(f.read_text())
        mains = [p for p in r["products"] if p.get("is_main_product")] or r["products"]
        assert len(mains) == 1, f"{f.name}: expected one main product"
        p = mains[0]
        mm, g = p.get("molar_mass_g_mol"), p.get("yield_g")
        rows.append(dict(
            journal_number=r["journal_number"], date=date.fromisoformat(r["date"]),
            reaction_name=r["reaction_name"].strip(), product_name=p["name"],
            sample_label=p.get("note"), formula=hill(p.get("inchi")),
            inchikey=p.get("inchikey"), amount_mmol=p.get("amount_mmol"),
            yield_g=g, molar_mass_g_mol=mm, yield_percent=p.get("yield_percent"),
            amount_check_mmol=round(1000 * g / mm, 5) if g and mm else None,
            target=target(r["reaction_name"]),
            sm_labels=[(s.get("note") or "", s["name"], s.get("amount_mmol"))
                       for s in r["starting_materials"]]))
    return rows


def group_substances(rows):
    """Union-find over aliases; display name = most common non-formula alias."""
    parent = {}
    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            a = parent[a]
        return a
    for r in rows:
        aliases = [a for a in (r["product_name"], r["formula"], r["inchikey"], r["target"]) if a]
        for a in aliases[1:]:
            parent[find(a)] = find(aliases[0])
    names = defaultdict(Counter)
    for r in rows:
        names[find(r["product_name"])].update(
            a for a in (r["product_name"], r["target"]) if not FORMULA.match(a))
    for r in rows:
        r["substance"] = names[find(r["product_name"])].most_common(1)[0][0]


def find_links(rows):
    by_label = {r["sample_label"]: r for r in rows if r["sample_label"]}
    links = []
    for r in rows:
        for note, name, mmol in r["sm_labels"]:
            m = re.match(r"^(.+)-\d+$", note)
            src = by_label.get(m.group(1)) if m else None
            if src and src is not r:
                assert src["date"] <= r["date"], f"{note}: used before it was made"
                links.append(dict(source=src["journal_number"], source_label=src["sample_label"],
                                  target=r["journal_number"], used_sample=note,
                                  used_as=name, used_mmol=mmol))
    return links


def row_order(rows, links):
    """Rows by first appearance; the substance feeding most links goes in the middle
    so arrows to rows above and below do not cross intermediate rows."""
    first = {}
    for r in sorted(rows, key=lambda r: r["date"]):
        first.setdefault(r["substance"], r["date"])
    order = sorted(first, key=first.get)
    sub = {r["journal_number"]: r["substance"] for r in rows}
    out = Counter(sub[l["source"]] for l in links if sub[l["source"]] != sub[l["target"]])
    if out:
        hub = out.most_common(1)[0][0]
        order.remove(hub)
        order.insert(len(order) // 2, hub)
    return order[::-1]  # matplotlib y grows upward; keep first row on top


def area(r):
    return r["amount_mmol"] * PT_PER_MMOL if r["amount_mmol"] else EMPTY_AREA


def place_labels(fig, ax, rows, xy, arrows):
    """Greedy: try spots around each circle, nearest first; reject any spot that
    overlaps an earlier label, any circle, a link arrow or a leader line.  Asserts every label found a spot."""
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    to_px = ax.transData.transform
    pt = fig.dpi / 72
    circles = []
    for r in rows:
        cx, cy = to_px(xy[r["journal_number"]])
        rad = math.sqrt(area(r)) / 2 * pt + 1
        circles.append((cx - rad, cy - rad, cx + rad, cy + rad))
    def hit(a, b, pad=2):
        return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])
    # plain polylines: intersects_bbox misreads the arrowhead's CLOSEPOLY vertex
    paths = [MplPath(poly) for a in arrows for poly in
             a.get_transform().transform_path(a.get_path()).to_polygons(closed_only=False)]
    placed = []
    for r, c in sorted(zip(rows, circles), key=lambda t: t[0]["date"]):
        cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
        rad = (c[2] - c[0]) / 2 / pt + 2.5
        cands = [(0, rad, "center", "bottom"), (0, -rad, "center", "top"),
                 (rad, 0, "left", "center"), (-rad, 0, "right", "center")]
        for k in (7, 14):  # detached spots, joined by a leader line
            d = rad + k
            cands += [(0, d, "center", "bottom"), (0, -d, "center", "top"),
                      (d, d, "left", "bottom"), (-d, d, "right", "bottom"),
                      (d, -d, "left", "top"), (-d, -d, "right", "top")]
        for dx, dy, ha, va in cands:
            far = math.hypot(dx, dy) > rad + 0.1
            t = ax.annotate(r["journal_number"], xy[r["journal_number"]], xytext=(dx, dy),
                            textcoords="offset points", ha=ha, va=va, fontsize=7, color=INK,
                            arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.4, shrinkA=0,
                                            shrinkB=math.sqrt(area(r)) / 2) if far else None)
            t.update_positions(rend)
            bb = Text.get_window_extent(t, rend)  # text only, not the leader line
            box = Bbox.from_extents(bb.x0, bb.y0, bb.x1, bb.y1)
            # leader: circle centre -> label anchor; checked against labels only
            leader = MplPath([(cx, cy), (cx + dx * pt, cy + dy * pt)]) if far else None
            ok = (not any(hit(box.extents, o.extents) for o in placed)
                  and not any(hit(box.extents, x) for x in circles if x is not c)
                  and not any(q.intersects_bbox(box.padded(2), filled=False) for q in paths)
                  and not (leader and any(leader.intersects_bbox(o.padded(2), filled=False) for o in placed)))
            if ok:
                placed.append(box)
                if leader:
                    paths.append(leader)
                break
            t.remove()
        else:
            raise AssertionError(f"no free label position for {r['journal_number']}")


def plot(rows, links, order, out):
    fig, ax = plt.subplots(figsize=(7.0, 2.6), dpi=300)
    ypos = {s: i for i, s in enumerate(order)}
    xy = {r["journal_number"]: (mdates.date2num(r["date"]), ypos[r["substance"]]) for r in rows}
    byj = {r["journal_number"]: r for r in rows}

    arrows = []
    for l in links:
        s, t = byj[l["source"]], byj[l["target"]]
        arrows.append(ax.add_patch(FancyArrowPatch(
            xy[l["source"]], xy[l["target"]], arrowstyle="-|>", mutation_scale=7,
            connectionstyle="arc3,rad=-0.12", color=MUTED, lw=0.7, zorder=1,
            shrinkA=math.sqrt(area(s)) / 2 + 1.5, shrinkB=math.sqrt(area(t)) / 2 + 1.5)))
    have = [r for r in rows if r["amount_mmol"]]
    miss = [r for r in rows if not r["amount_mmol"]]
    ax.scatter([xy[r["journal_number"]][0] for r in have], [xy[r["journal_number"]][1] for r in have],
               s=[area(r) for r in have], color=BLUE, edgecolor="white", lw=0.8, zorder=3)
    ax.scatter([xy[r["journal_number"]][0] for r in miss], [xy[r["journal_number"]][1] for r in miss],
               s=EMPTY_AREA, facecolor="white", edgecolor=BLUE, lw=1.0, zorder=3)

    ax.set_yticks(range(len(order)), [pretty(s) for s in order], fontsize=7.5, color=INK)
    ax.set_ylim(-0.6, len(order) - 0.4)
    dmin, dmax = min(r["date"] for r in rows), max(r["date"] for r in rows)
    pad = (dmax - dmin).days * 0.04
    ax.set_xlim(mdates.date2num(dmin) - pad, mdates.date2num(dmax) + pad)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
    ax.tick_params(axis="x", labelsize=7, colors=MUTED)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)

    h = [ax.scatter([], [], s=v * PT_PER_MMOL, color=BLUE, edgecolor="white") for v in LEGEND_MMOL]
    h.append(ax.scatter([], [], s=EMPTY_AREA, facecolor="white", edgecolor=BLUE))
    ax.legend(h, [f"{v:g}" for v in LEGEND_MMOL] + ["n.r."], title="Isolated product (mmol)",
              title_fontsize=7, fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1.0),
              frameon=False, labelspacing=1.6, borderpad=0.2, handletextpad=0.8)
    fig.tight_layout()
    place_labels(fig, ax, rows, xy, arrows)
    for ext in ("png", "pdf"):
        fig.savefig(out / f"product_timeline.{ext}", bbox_inches="tight")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--out", default=HERE / "outputs")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = load(a.data)
    group_substances(rows)
    links = find_links(rows)
    order = row_order(rows, links)
    plot(rows, links, order, out)

    cols = ["journal_number", "date", "substance", "product_name", "sample_label", "formula",
            "amount_mmol", "yield_g", "molar_mass_g_mol", "amount_check_mmol", "yield_percent",
            "reaction_name"]
    with open(out / "product_timeline.csv", "w", newline="") as f:
        w = csv.DictWriter(f, cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["date"]))
    with open(out / "product_links.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["source", "source_label", "target", "used_sample", "used_as", "used_mmol"])
        w.writeheader()
        w.writerows(links)

    for r in sorted(rows, key=lambda r: r["date"]):
        print(f"{r['journal_number']:8} {r['date']}  {r['substance']:24} {r['sample_label']:9} "
              f"{r['amount_mmol'] if r['amount_mmol'] is not None else 'n.r.'}")
    for l in links:
        print(f"{l['source']} ({l['source_label']}) -> {l['target']} as {l['used_sample']}")


if __name__ == "__main__":
    main()
