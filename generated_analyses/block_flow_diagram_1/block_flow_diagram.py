"""Block flow diagram of one experiment's procedure.

One box per recorded step, arrows in reading order, the Prep / Reaction /
Workup sections on separate shaded bands.  Each box shows the step type, the
parameters recorded for it (reagent and amount, temperature, time, ...) and
the vessel.  Rows hold at most five boxes and run boustrophedon (left to
right, then right to left), so every row turn is a short vertical arrow.

Reagent amounts that the step itself does not carry are looked up in
`starting_materials` by name.

Schema-generic: any `$xml_type` and any `_parameter` is rendered, so the same
script serves the chemotion_eln and excel_workbooks records (the latter carry
no `_vessel` and use extra keys such as `_method`).

Dependencies: matplotlib.
Rerun:
    python3 block_flow_diagram.py
    python3 block_flow_diagram.py --record AD-R11
    python3 block_flow_diagram.py --data <assembled dir> --record "WAT-Ch-044 L-Ile Methylester"
    python3 block_flow_diagram.py --selftest
"""

import argparse
import csv
import json
import re
import sys
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "cases/chemotion_eln/output/run_2026_07_17_19_26/assembled"
OUT = Path(__file__).resolve().parent / "outputs"
RECORD = "AD-R10"

COLS = 5            # boxes per row, as requested
LEFT = 0.46         # inches reserved for the rotated phase labels
BOX_W, BOX_H = 1.112, 0.90      # BOX_H is re-fitted to the tallest box
COL_GAP, ROW_GAP, PHASE_GAP = 0.11, 0.26, 0.20
PAD = 0.055         # text inset inside a box
TOP, BOT = 0.52, 0.10
FS_TRY = (6.0, 5.6, 5.2, 4.8)   # body font sizes, largest that fits wins
LINE = 1.22                     # line height in font sizes
EQ_MAX = 50         # equivalents above this are solvent bookkeeping, not information
NOTE_CHARS = 60     # fallback note length for steps with no recorded parameters

ARROW = "#444444"
PHASE_STYLE = {
    "Prep":     ("#2F6DB5", "#EAF1FA"),
    "Reaction": ("#C7442E", "#FBEDEA"),
    "Workup":   ("#3F7A4A", "#EAF3EC"),
}
GREY_STYLE = ("#5A5A5A", "#F0F0F0")

UNIT = {"celsius": "°C", "kelvin": "K", "fahrenheit": "°F",
        "second": "s", "minute": "min", "hour": "h", "day": "d",
        "microgram": "µg", "milligram": "mg", "gram": "g", "kilogram": "kg",
        "microlitre": "µL", "millilitre": "mL", "litre": "L",
        "micromole": "µmol", "millimole": "mmol", "mole": "mol",
        "millibar": "mbar", "bar": "bar", "atm": "atm", "pascal": "Pa"}
STEP_NAME = {"HeatChill": "Heat / chill", "EvacuateAndRefill": "Evacuate & refill",
             "WashPhase": "Wash phase"}
PARAM_NAME = {"_temp": "T", "_time": "t", "_pressure": "p",
              "_stationary_phase": "stat. phase", "_phase_kept": "keep",
              "_repeat_interval": "interval", "_repeat": "repeats"}
SKIP = {"$xml_type", "_vessel", "_comment"}


# ---------------------------------------------------------------- formatting

def num(v):
    return f"{round(v, 2):g}" if isinstance(v, float) else f"{v:g}"


def fmt(v):
    """Render any schema value: quantity, solvent object, list or scalar."""
    if isinstance(v, dict):
        if "Value" in v:
            return f"{num(v['Value'])} {UNIT.get(v.get('Unit'), v.get('Unit', ''))}".strip()
        name = v.get("name", "")
        amount = fmt(v["amount"]) if v.get("amount") else ""
        return f"{name} {amount}".strip()
    if isinstance(v, list):
        return ", ".join(fmt(x) for x in v)
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)


def step_title(step, order):
    kind = step.get("$xml_type", "Step")
    name = STEP_NAME.get(kind) or re.sub(r"(?<!^)(?=[A-Z])", " ", kind)
    return f"{order}. {name}"


def material_amount(material):
    """Amount recorded in starting_materials, for steps that name no amount."""
    bits = []
    if material.get("volume_mL") is not None:
        bits.append(f"{num(material['volume_mL'])} mL")
    elif material.get("mass_g") is not None:
        bits.append(f"{num(material['mass_g'])} g")
    if material.get("amount_mmol") is not None:
        bits.append(f"{num(material['amount_mmol'])} mmol")
    eq = material.get("equivalents")
    if eq is not None and eq <= EQ_MAX:
        bits.append(f"{num(eq)} eq")
    return ", ".join(bits)


def step_params(step, materials, charged=None):
    """Parameter lines for one box, reagent (with its amount) first.

    `starting_materials` records the total charged per material, so that amount
    is attached only to the first step adding it; a later step re-using the same
    solvent (rinsing, reprecipitation) shows an amount only if it records one
    itself.  `charged` collects the material names already accounted for.
    """
    lines = []
    reagent = (step.get("_reagent") or "").strip()
    if reagent:
        key = reagent.lower()
        if step.get("_amount"):
            amount = fmt(step["_amount"])
        elif charged is not None and key in charged:
            amount = ""
        else:
            amount = material_amount(materials.get(key, {}))
            if charged is not None and amount:
                charged.add(key)
        lines.append(f"{reagent} – {amount}" if amount else reagent)
    for param, value in step.items():
        if param in SKIP or param == "_reagent" or (param == "_amount" and reagent):
            continue
        label = PARAM_NAME.get(param, param.lstrip("_").replace("_", " "))
        if isinstance(value, bool):
            if value:
                lines.append(label)
        else:
            lines.append(f"{label}: {fmt(value)}")
    if not lines:
        # nothing structured was recorded: fall back to the first clause of the note
        note = re.split(r"[;.\n]", step.get("_comment") or "")[0].strip()
        if note:
            lines.append(note if len(note) <= NOTE_CHARS
                         else note[:NOTE_CHARS - 1].rstrip() + "…")
    return lines


# ------------------------------------------------------------------- loading

def load_record(data_dir, record):
    for path in sorted(Path(data_dir).glob("*.json")):
        doc = json.load(path.open())
        if record in (doc.get("journal_number"), path.stem):
            return doc
    raise SystemExit(f"record {record!r} not found in {data_dir}")


def collect_steps(doc):
    """Flatten the procedure into (phase, step) pairs in recorded order."""
    materials = {m["name"].strip().lower(): m for m in doc.get("starting_materials", [])}
    charged, out = set(), []
    for phase, section in doc.get("procedure", {}).items():
        for step in (section or {}).get("Step", []):
            out.append((phase, step, step_title(step, len(out) + 1),
                        step_params(step, materials, charged)))
    return out


def layout(steps):
    """Boustrophedon placement; every phase starts a fresh row at column 0."""
    placed, row, col, direction, phase_now = [], -1, 0, 1, None
    for phase, step, title, params in steps:
        if phase != phase_now:            # new phase: new row, back to the left
            row, col, direction = row + 1, 0, 1
        elif 0 <= col + direction < COLS:
            col += direction
        else:                             # row turn: same column, other way round
            row, direction = row + 1, -direction
        phase_now = phase
        placed.append({"phase": phase, "step": step, "title": title,
                       "params": params, "row": row, "col": col})
    return placed


# ------------------------------------------------------------------- drawing

def fit_text(title, params, vessel):
    """Largest font size whose wrapped text fits the box; lines are clipped."""
    inner_w, inner_h = BOX_W - 2 * PAD, BOX_H - 2 * PAD
    for fs in FS_TRY:
        width = max(8, int(inner_w * 72 / (0.52 * fs)))
        head = textwrap.wrap(title, width)
        body = [w for line in params for w in textwrap.wrap(line, width)]
        foot = textwrap.wrap(vessel, width) if vessel else []
        n = len(head) + len(body) + len(foot) + (0.4 if body else 0)
        if n * fs * LINE / 72 <= inner_h or fs == FS_TRY[-1]:
            budget = int(inner_h * 72 / (fs * LINE))
            while len(head) + len(body) + len(foot) > budget and body:
                body.pop()
                if body:
                    body[-1] = body[-1][:width - 1] + "…"
            return fs, head, body, foot
    raise AssertionError("unreachable")


def box_height(placed):
    """Just tall enough for the fullest box at the largest font size."""
    fs = FS_TRY[0]
    width = max(8, int((BOX_W - 2 * PAD) * 72 / (0.52 * fs)))
    tallest = 0
    for box in placed:
        vessel = box["step"].get("_vessel", "")
        lines = len(textwrap.wrap(box["title"], width)) \
            + sum(len(textwrap.wrap(line, width)) for line in box["params"]) \
            + (len(textwrap.wrap(f"in {vessel}", width)) if vessel else 0)
        tallest = max(tallest, lines)
    return round((tallest + 0.4) * fs * LINE / 72 + 2 * PAD, 3)


def draw(doc, placed, png):
    global BOX_H
    BOX_H = box_height(placed)
    nrows = placed[-1]["row"] + 1
    phase_rows = {}
    for box in placed:
        phase_rows.setdefault(box["phase"], []).append(box["row"])
    starts = {rows[0] for rows in phase_rows.values()}

    extra = {}
    running = 0.0
    for r in range(nrows):
        if r and r in starts:
            running += PHASE_GAP
        extra[r] = running

    def y_of(row):
        return TOP + row * (BOX_H + ROW_GAP) + extra[row]

    def x_of(col):
        return LEFT + col * (BOX_W + COL_GAP)

    width = LEFT + COLS * BOX_W + (COLS - 1) * COL_GAP + 0.10
    height = y_of(nrows - 1) + BOX_H + BOT
    fig = plt.figure(figsize=(width, height))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)
    ax.axis("off")

    for phase, rows in phase_rows.items():
        edge, fill = PHASE_STYLE.get(phase, GREY_STYLE)
        top, bottom = y_of(min(rows)) - 0.09, y_of(max(rows)) + BOX_H + 0.09
        ax.add_patch(Rectangle((0.16, top), width - 0.26, bottom - top,
                               facecolor=fill, edgecolor="none", zorder=0))
        ax.text(0.30, (top + bottom) / 2, phase.upper(), rotation=90, color=edge,
                ha="center", va="center", fontsize=7.5, fontweight="bold", zorder=1)

    for box in placed:
        edge, _ = PHASE_STYLE.get(box["phase"], GREY_STYLE)
        x, y = x_of(box["col"]), y_of(box["row"])
        ax.add_patch(FancyBboxPatch((x, y), BOX_W, BOX_H, zorder=2,
                                    boxstyle="round,pad=0,rounding_size=0.05",
                                    facecolor="white", edgecolor=edge, linewidth=0.9))
        vessel = box["step"].get("_vessel", "")
        fs, head, body, foot = fit_text(box["title"], box["params"],
                                        f"in {vessel}" if vessel else "")
        ty = y + PAD
        for line in head:
            ax.text(x + PAD, ty, line, fontsize=fs + 0.4, fontweight="bold",
                    color=edge, va="top", ha="left", zorder=3)
            ty += (fs + 0.4) * LINE / 72
        ty += 0.4 * fs * LINE / 72 if body else 0
        for line in body:
            ax.text(x + PAD, ty, line, fontsize=fs, color="#1A1A1A",
                    va="top", ha="left", zorder=3)
            ty += fs * LINE / 72
        for line in foot:
            ax.text(x + PAD, ty, line, fontsize=fs - 0.3, color="#6B6B6B",
                    style="italic", va="top", ha="left", zorder=3)
            ty += fs * LINE / 72

    for before, after in zip(placed, placed[1:]):
        x0, y0 = x_of(before["col"]), y_of(before["row"])
        x1, y1 = x_of(after["col"]), y_of(after["row"])
        if before["row"] == after["row"]:                     # along the row
            forward = after["col"] > before["col"]
            start = (x0 + BOX_W, y0 + BOX_H / 2) if forward else (x0, y0 + BOX_H / 2)
            end = (x1, y1 + BOX_H / 2) if forward else (x1 + BOX_W, y1 + BOX_H / 2)
        else:                                                 # row turn / phase change
            sx, ex = x0 + BOX_W / 2, x1 + BOX_W / 2
            mid = (y0 + BOX_H + y1) / 2
            if sx != ex:                                      # elbow through the gap
                ax.plot([sx, sx, ex], [y0 + BOX_H, mid, mid],
                        color=ARROW, linewidth=0.8, solid_capstyle="round", zorder=4)
            start, end = (ex, mid if sx != ex else y0 + BOX_H), (ex, y1)
        ax.annotate("", xy=end, xytext=start, zorder=4,
                    arrowprops=dict(arrowstyle="-|>,head_width=0.10,head_length=0.22",
                                    color=ARROW, linewidth=0.8,
                                    shrinkA=0.5, shrinkB=0.5))

    product = next((p for p in doc.get("products", []) if p.get("is_main_product")),
                   (doc.get("products") or [{}])[0])
    ax.text(0.16, 0.17, f"{doc.get('journal_number')} · {doc.get('reaction_name')}",
            fontsize=8.5, fontweight="bold", color="#1A1A1A", va="center", ha="left")
    subtitle = " · ".join(filter(None, [
        doc.get("date"),
        f"{product.get('name')}: {num(product['yield_g'])} g, "
        f"{num(product['yield_percent'])} % yield" if product.get("yield_g") else None,
        f"{len(placed)} steps"]))
    ax.text(0.16, 0.36, subtitle, fontsize=7.2, color="#5A5A5A", va="center", ha="left")

    fig.savefig(png, dpi=400)
    fig.savefig(png.with_suffix(".pdf"))
    plt.close(fig)
    return width, height


def write_csv(placed, path):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["order", "phase", "row", "col", "step_type", "vessel",
                         "parameters", "comment"])
        for order, box in enumerate(placed, 1):
            writer.writerow([order, box["phase"], box["row"], box["col"],
                             box["step"].get("$xml_type", ""),
                             box["step"].get("_vessel", ""),
                             "; ".join(box["params"]),
                             box["step"].get("_comment", "")])


# ------------------------------------------------------------------ selftest

def selftest():
    assert fmt({"Value": 1.5, "Unit": "hour"}) == "1.5 h"
    assert fmt({"Value": 120, "Unit": "celsius"}) == "120 °C"
    assert fmt([{"name": "n-hexane", "amount": {"Value": 15, "Unit": "millilitre"}}]) \
        == "n-hexane 15 mL"
    assert fmt({"Value": 24.885049, "Unit": "millilitre"}) == "24.89 mL"
    assert step_title({"$xml_type": "EvacuateAndRefill"}, 3) == "3. Evacuate & refill"
    assert step_title({"$xml_type": "Sonicate"}, 1) == "1. Sonicate"
    assert material_amount({"mass_g": 0.25042, "amount_mmol": 0.37125, "equivalents": 1}) \
        == "0.25 g, 0.37 mmol, 1 eq"
    assert "eq" not in material_amount({"volume_mL": 20, "equivalents": 664.45})

    mats = {"tapp": {"mass_g": 0.25042, "equivalents": 1}, "thf": {"volume_mL": 20}}
    assert step_params({"$xml_type": "Add", "_reagent": "TAPP  "}, mats) \
        == ["TAPP – 0.25 g, 1 eq"]
    charged, add_thf = set(), {"$xml_type": "Add", "_reagent": "THF"}
    assert step_params(add_thf, mats, charged) == ["THF – 20 mL"]
    assert step_params(add_thf, mats, charged) == ["THF"]    # re-use: not charged twice
    assert step_params({"$xml_type": "Add", "_reagent": "THF",
                        "_amount": {"Value": 3, "Unit": "millilitre"}}, mats, charged) \
        == ["THF – 3 mL"]                                 # unless it records one
    # unknown parameter and unknown step type still render (excel_workbooks case)
    assert step_params({"$xml_type": "Evaporate", "_method": "vacuum"}, {}) \
        == ["method: vacuum"]
    # no parameters recorded at all: first clause of the free-text note
    assert step_params({"$xml_type": "Evaporate", "_comment": "Rotovap"}, {}) == ["Rotovap"]
    assert step_params({"$xml_type": "Filter", "_comment": "a" * 90 + "; rest"}, {}) \
        == ["a" * (NOTE_CHARS - 1) + "…"]
    assert step_params({"$xml_type": "Wait", "_comment": ""}, {}) == []
    assert step_params({"$xml_type": "HeatChill", "_reflux": True,
                        "_temp": {"Value": 85, "Unit": "celsius"}}, {}) \
        == ["reflux", "T: 85 °C"]   # recorded key order is kept

    # boustrophedon: rows of five, each row turn stays in the same column
    steps = [("Prep", {}, "", []) for _ in range(12)] + \
            [("Reaction", {}, "", []) for _ in range(2)]
    cells = [(b["row"], b["col"]) for b in layout(steps)]
    assert [c for r, c in cells[:5]] == [0, 1, 2, 3, 4]
    assert [c for r, c in cells[5:10]] == [4, 3, 2, 1, 0]
    assert cells[4][1] == cells[5][1] and cells[4][0] + 1 == cells[5][0]
    assert cells[12] == (3, 0) and cells[13] == (3, 1)   # Reaction: new row, left edge
    assert all(0 <= c < COLS for _, c in cells)

    fs, head, body, foot = fit_text("1. Add", ["x" * 400], "in flask")
    assert fs == FS_TRY[-1] and body[-1].endswith("…")
    print("selftest ok")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=DATA, type=Path)
    parser.add_argument("--output", default=OUT, type=Path)
    parser.add_argument("--record", default=RECORD)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()

    doc = load_record(args.data, args.record)
    steps = collect_steps(doc)
    placed = layout(steps)
    args.output.mkdir(parents=True, exist_ok=True)
    stem = f"block_flow_diagram_{doc['journal_number'].replace(' ', '_')}"
    size = draw(doc, placed, args.output / f"{stem}.png")
    write_csv(placed, args.output / f"{stem}.csv")

    print(f"{doc['journal_number']}: {len(placed)} steps, "
          f"{placed[-1]['row'] + 1} rows, figure {size[0]:.2f} x {size[1]:.2f} in")
    for phase, section in doc["procedure"].items():
        print(f"  {phase}: {len(section.get('Step', []))} steps")
    for box in placed:
        if not box["params"]:
            print(f"  no recorded parameters: {box['title']}")
        if not box["step"].get("_vessel"):
            print(f"  no vessel recorded: {box['title']}")


if __name__ == "__main__":
    sys.exit(main())
