#!/usr/bin/env python3
"""Check each reviewer-reported issue against an Excel conversion's records.

Prints a per-item status (FIXED / NOT FIXED / N/A) with a one-line reason.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OUTPUT_DIR: Path


def load(ch: str) -> dict | None:
    matches = list(OUTPUT_DIR.glob(f"WAT-Ch-{ch} *.json"))
    if not matches:
        return None
    return json.loads(matches[0].read_text(encoding="utf-8"))


def steps(doc, section):
    return doc.get("procedure", {}).get(section, {}).get("Step", []) or []


def has_step(doc, section, predicate) -> bool:
    return any(predicate(s) for s in steps(doc, section))


def count_steps(doc, section, predicate) -> int:
    return sum(1 for s in steps(doc, section) if predicate(s))


def reagent_in(s, *needles):
    r = (s.get("_reagent") or "").lower()
    return any(n.lower() in r for n in needles)


def report(label: str, ok: bool | None, detail: str = "") -> None:
    if ok is None:
        tag = "N/A "
    elif ok:
        tag = "PASS"
    else:
        tag = "FAIL"
    print(f"  [{tag}] {label}{'  — ' + detail if detail else ''}")


PASS = FAIL = NA = 0


def check(label: str, ok: bool | None, detail: str = ""):
    global PASS, FAIL, NA
    if ok is None:
        NA += 1
    elif ok:
        PASS += 1
    else:
        FAIL += 1
    report(label, ok, detail)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def run() -> int:
    # ---------------- Ch-044 ----------------
    section("Ch-044  L-Ile Methylester")
    d = load("044")
    if d:
        has_aminoester = has_step(d, "Prep", lambda s: reagent_in(s, "L-Isoleucin"))
        check("Prep contains Add L-Isoleucin (Aminosäure resolved)", has_aminoester)

        rxn = steps(d, "Reaction")
        # Want HeatChill 25 °C BEFORE the long Wait 48 h
        heatchill_25_before_wait = False
        for i, s in enumerate(rxn):
            if s.get("$xml_type") == "HeatChill" and (s.get("_temp") or {}).get("Value") in (25, 25.0):
                for s2 in rxn[i + 1 :]:
                    if s2.get("$xml_type") == "Wait" and (s2.get("_time") or {}).get("Value") in (48, 48.0):
                        heatchill_25_before_wait = True
                        break
        check("Reaction: HeatChill 25 °C precedes Wait 48 h", heatchill_25_before_wait)

        # MeOH workup re-dissolution should NOT carry an _amount
        meoh_workup = [s for s in steps(d, "Workup") if reagent_in(s, "MeOH")]
        invented = [s for s in meoh_workup if s.get("_amount") is not None]
        check(
            "Workup: MeOH re-dissolution without invented amount",
            len(invented) == 0,
            f"{len(meoh_workup)} MeOH adds, {len(invented)} with invented amount",
        )

    # ---------------- Ch-045 ----------------
    section("Ch-045  L-Ile oNs-Schützung")
    d = load("045")
    if d:
        prep_has_edukt = has_step(d, "Prep", lambda s: reagent_in(s, "L-Ile-Me HCl 044", "L-Ile"))
        check("Prep contains Add Edukt (L-Ile-Me HCl 044)", prep_has_edukt)

        rxn = steps(d, "Reaction")
        # Want Add DCM(NsCl) before Add 2-NsCl
        dcm_before_nscl = False
        for i, s in enumerate(rxn):
            if s.get("$xml_type") == "Add" and "DCM" in (s.get("_reagent") or "") and "NsCl" in (s.get("_reagent") or ""):
                for s2 in rxn[i + 1 :]:
                    if reagent_in(s2, "2-NsCl") and s2.get("$xml_type") == "Add":
                        dcm_before_nscl = True
                        break
        check("Reaction: Add DCM (NsCl) precedes Add 2-NsCl", dcm_before_nscl)

    # ---------------- Ch-061 ----------------
    section("Ch-061  L-Ile Methylester")
    d = load("061")
    if d:
        meoh_workup = [s for s in steps(d, "Workup") if reagent_in(s, "MeOH")]
        invented = [s for s in meoh_workup if s.get("_amount") is not None]
        check(
            "Workup MeOH without invented amount",
            len(invented) == 0,
            f"{len(meoh_workup)} MeOH adds, {len(invented)} with invented amount",
        )

    # ---------------- Ch-063 ----------------
    section("Ch-063  L-Ile oNs-Schützung")
    d = load("063")
    if d:
        rxn = steps(d, "Reaction")
        dcm_before_nscl = False
        for i, s in enumerate(rxn):
            if s.get("$xml_type") == "Add" and "DCM" in (s.get("_reagent") or "") and "NsCl" in (s.get("_reagent") or ""):
                for s2 in rxn[i + 1 :]:
                    if reagent_in(s2, "2-NsCl", "NsCl") and s2.get("$xml_type") == "Add":
                        dcm_before_nscl = True
                        break
        check("Reaction: Add DCM (NsCl) precedes Add 2-NsCl", dcm_before_nscl)

    # ---------------- Ch-066 ----------------
    section("Ch-066  Reduktion Aminoester")
    d = load("066")
    if d:
        # Expect an Add of THF in Reaction BEFORE Add LAH (since LAH is in THF)
        rxn = steps(d, "Reaction")
        thf_before_lah = False
        for i, s in enumerate(rxn):
            if s.get("$xml_type") == "Add" and "THF" in (s.get("_reagent") or ""):
                for s2 in rxn[i + 1 :]:
                    if reagent_in(s2, "LAH") and s2.get("$xml_type") == "Add":
                        thf_before_lah = True
                        break
        check(
            "Reaction: Add THF precedes Add LAH",
            thf_before_lah,
            "Excel lacks a 'THF (LAH)' row — fix needs corrected Excel",
        )

    # ---------------- Ch-067 ----------------
    section("Ch-067  DMP-Oxidation")
    d = load("067")
    if d:
        prep_or_rxn_has_edukt = any(
            has_step(d, sec, lambda s: reagent_in(s, "Alkohol 066"))
            for sec in ("Prep", "Reaction")
        )
        check("procedure contains Add Edukt (Alkohol 066)", prep_or_rxn_has_edukt)

        dee_extracts = [s for s in steps(d, "Workup") if s.get("$xml_type") == "Extract" and "DEE" in (s.get("_solvent") or "")]
        ok = all(e.get("_phase_kept") == "organic" for e in dee_extracts) and len(dee_extracts) >= 1
        check("Workup Extract DEE _phase_kept = organic", ok)

    # ---------------- Ch-081 ----------------
    section("Ch-081  Reduktion Aminoester (ohne Aufarbeitung)")
    d = load("081")
    if d:
        rxn = steps(d, "Reaction")
        thf_before_lah = False
        for i, s in enumerate(rxn):
            if s.get("$xml_type") == "Add" and "THF" in (s.get("_reagent") or ""):
                for s2 in rxn[i + 1 :]:
                    if reagent_in(s2, "LAH") and s2.get("$xml_type") == "Add":
                        thf_before_lah = True
                        break
        check("Reaction: Add THF precedes Add LAH", thf_before_lah)

    # ---------------- Ch-082 ----------------
    section("Ch-082  DMP-Oxidation")
    d = load("082")
    if d:
        prep_or_rxn_has_edukt = any(
            has_step(d, sec, lambda s: reagent_in(s, "Alkohol 081", "Aminoalkohol"))
            for sec in ("Prep", "Reaction")
        )
        check("procedure contains Add Edukt (Alkohol 081 / Aminoalkohol)", prep_or_rxn_has_edukt)

        dee_extracts = [s for s in steps(d, "Workup") if s.get("$xml_type") == "Extract" and "DEE" in (s.get("_solvent") or "")]
        ok = all(e.get("_phase_kept") == "organic" for e in dee_extracts) and len(dee_extracts) >= 1
        check("Workup Extract DEE _phase_kept = organic", ok)

    # ---------------- Ch-083 ----------------
    section("Ch-083  Cyclisierung FeCl3")
    d = load("083")
    if d:
        rxn = steps(d, "Reaction")
        dee_before_fecl3 = False
        for i, s in enumerate(rxn):
            if s.get("$xml_type") == "Add" and "DEE" in (s.get("_reagent") or ""):
                for s2 in rxn[i + 1 :]:
                    if reagent_in(s2, "FeCl3") and s2.get("$xml_type") == "Add":
                        dee_before_fecl3 = True
                        break
        check("Reaction: Add DEE precedes Add FeCl3", dee_before_fecl3)

    # ---------------- Ch-085 ----------------
    section("Ch-085  L-Ile Methylester")
    d = load("085")
    if d:
        prep_has_edukt = has_step(d, "Prep", lambda s: reagent_in(s, "L-Isoleucin", "L-Ile"))
        check("Prep contains Add Edukt (Aminosäure → L-Isoleucin)", prep_has_edukt)

        meoh_workup = [s for s in steps(d, "Workup") if reagent_in(s, "MeOH")]
        invented = [s for s in meoh_workup if s.get("_amount") is not None]
        check(
            "Workup MeOH without invented amount",
            len(invented) == 0,
            f"{len(meoh_workup)} MeOH adds, {len(invented)} with invented amount",
        )

    # ---------------- Ch-087 ----------------
    section("Ch-087  L-Ile oNs-Schützung")
    d = load("087")
    if d:
        products = d.get("products", [])
        bad_products = [p for p in products if not p.get("yield_g") and not p.get("yield_percent")]
        check(
            "No yieldless 'Misch Diast (?)' product",
            len(bad_products) == 0,
            f"yieldless products: {[p.get('name') for p in bad_products]}",
        )

        prep_has_edukt = has_step(d, "Prep", lambda s: reagent_in(s, "L-Ile-Me HCl"))
        check("Prep contains Add Edukt", prep_has_edukt)

        rxn = steps(d, "Reaction")
        dcm_before_nscl = False
        for i, s in enumerate(rxn):
            if s.get("$xml_type") == "Add" and "DCM" in (s.get("_reagent") or "") and "NsCl" in (s.get("_reagent") or ""):
                for s2 in rxn[i + 1 :]:
                    if reagent_in(s2, "NsCl") and s2.get("$xml_type") == "Add":
                        dcm_before_nscl = True
                        break
        check("Reaction: Add DCM (NsCl) precedes Add 2-NsCl", dcm_before_nscl)

        dcm_extracts = [s for s in steps(d, "Workup") if s.get("$xml_type") == "Extract" and "DCM" in (s.get("_solvent") or "")]
        ok = all(e.get("_phase_kept") == "organic" for e in dcm_extracts) and len(dcm_extracts) >= 1
        check("Workup Extract DCM _phase_kept = organic", ok)

    # ---------------- Ch-089 ----------------
    section("Ch-089  Reduktion Aminoester ohne Aufarbeitung")
    d = load("089")
    if d:
        rxn = steps(d, "Reaction")
        thf_before_lah = False
        for i, s in enumerate(rxn):
            if s.get("$xml_type") == "Add" and "THF" in (s.get("_reagent") or ""):
                for s2 in rxn[i + 1 :]:
                    if reagent_in(s2, "LAH") and s2.get("$xml_type") == "Add":
                        thf_before_lah = True
                        break
        check("Reaction: Add THF precedes Add LAH", thf_before_lah)

        wasser_adds = [s for s in steps(d, "Workup") if reagent_in(s, "Wasser", "H2O")]
        with_amount = [s for s in wasser_adds if s.get("_amount") is not None]
        check(
            "Workup: Wasser uses volume from table",
            len(with_amount) >= 1,
            f"{len(wasser_adds)} Wasser adds, {len(with_amount)} with amount",
        )

    # ---------------- Ch-090 ----------------
    section("Ch-090  DMP-Oxidation")
    d = load("090")
    if d:
        dee_extracts = [s for s in steps(d, "Workup") if s.get("$xml_type") == "Extract" and "DEE" in (s.get("_solvent") or "")]
        ok = all(e.get("_phase_kept") == "organic" for e in dee_extracts) and len(dee_extracts) >= 1
        check("Workup Extract DEE _phase_kept = organic", ok)

    # ---------------- Ch-091 ----------------
    section("Ch-091  Cyclisierung FeCl3")
    d = load("091")
    if d:
        prep_or_rxn_has_edukt = any(
            has_step(d, sec, lambda s: reagent_in(s, "Aminoaldehyd 090", "Aldehyd 090"))
            for sec in ("Prep", "Reaction")
        )
        check("procedure contains Add Edukt (Aminoaldehyd 090)", prep_or_rxn_has_edukt)

        rxn = steps(d, "Reaction")
        dee_before_fecl3 = False
        for i, s in enumerate(rxn):
            if s.get("$xml_type") == "Add" and "DEE" in (s.get("_reagent") or ""):
                for s2 in rxn[i + 1 :]:
                    if reagent_in(s2, "FeCl3") and s2.get("$xml_type") == "Add":
                        dee_before_fecl3 = True
                        break
        check("Reaction: Add DEE precedes Add FeCl3", dee_before_fecl3)

    # ---------------- Fluorinations ----------------
    section("Fluorierungen — Entgasen-Note")
    entgasen_targets = [
        "113", "114", "116", "117", "118", "119", "120",
        "122", "123", "127", "130", "131", "132", "133",
        "234", "242",
    ]
    for ch in entgasen_targets:
        d = load(ch)
        if not d:
            check(f"Ch-{ch}", None, "file missing")
            continue
        evac = [s for s in steps(d, "Prep") if s.get("$xml_type") == "EvacuateAndRefill"]
        ok = any("Entgasen" in (s.get("_comment") or "") for s in evac)
        check(f"Ch-{ch}  EvacuateAndRefill _comment contains 'Entgasen'", ok)

    section("Fluorierungen — zwei Add AcN in Reaction")
    acn_targets = [
        "115", "116", "117", "118", "121", "122", "123", "125",
        "129", "130", "133", "234", "239", "240", "241", "242",
    ]
    for ch in acn_targets:
        d = load(ch)
        if not d:
            check(f"Ch-{ch}", None, "file missing")
            continue
        acn_adds = count_steps(d, "Reaction", lambda s: s.get("$xml_type") == "Add" and "AcN" in (s.get("_reagent") or ""))
        check(f"Ch-{ch}  has >=2 Add AcN in Reaction", acn_adds >= 2, f"found {acn_adds}")

    section("Ch-122 — NaBH4 (x3)")
    d = load("122")
    if d:
        nabh4_adds = count_steps(d, "Reaction", lambda s: s.get("$xml_type") == "Add" and (s.get("_reagent") or "").startswith("NaBH4"))
        check("Reaction: 3 Add NaBH4 steps", nabh4_adds == 3, f"found {nabh4_adds}")

    # ---------------- Summary ----------------
    print()
    print(f"=== TOTAL: PASS={PASS}  FAIL={FAIL}  N/A={NA} ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="Folder of converted Excel records (assembled/ or results/).")
    args = parser.parse_args()
    if not args.input.is_dir() or not any(args.input.glob("WAT-Ch-*.json")):
        parser.error(f"No converted Excel records found in {args.input}")
    OUTPUT_DIR = args.input
    sys.exit(run())
