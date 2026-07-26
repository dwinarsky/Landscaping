#!/usr/bin/env python3
"""Check the transcribed data against the blueprint's own arithmetic.

The plant legend states a quantity per key. The drawing states a count per
callout. Those two must agree, per key and in total, which makes the legend a
checksum over roughly two hundred hand-read hexagons: any misread key or digit
shows up as a per-key mismatch rather than passing silently.

Also enforces the structural rule that matters most in this project: plant keys
are scoped per sheet. Sheet 3 and sheet 4 reuse the same two-letter keys for
different plants (HA is a day lily on one and Toyon on the other), so any
lookup that ignores the sheet is a bug.

Exits non-zero if anything fails.

Usage:  python3 tools/validate.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load(path: pathlib.Path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def point_in_poly(x: float, y: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xt = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < xt:
                inside = not inside
    return inside


def check_sheet(sheet: dict, errors: list[str], warnings: list[str]) -> None:
    sid = sheet["id"]
    d = DATA / sid
    print(f"\n=== {sid} ({sheet['label']}, sheet {sheet['sheetNumber']}) ===")

    plants = load(d / "plants.json")
    callouts = load(d / "callouts.json")
    zones = load(d / "zones.json")

    if plants is None:
        errors.append(f"{sid}: plants.json missing")
        return

    by_key = {p["key"]: p for p in plants}
    if len(by_key) != len(plants):
        errors.append(f"{sid}: duplicate keys in plants.json")

    legend_total = sum(p["qty"] for p in plants)
    print(f"  legend: {len(plants)} species, {legend_total} plants")
    if legend_total != sheet["plantTotal"]:
        errors.append(f"{sid}: legend sums to {legend_total} but sheets.json "
                      f"says plantTotal={sheet['plantTotal']}")
    if len(plants) != sheet["speciesCount"]:
        errors.append(f"{sid}: {len(plants)} species but sheets.json says "
                      f"speciesCount={sheet['speciesCount']}")

    if callouts is None:
        warnings.append(f"{sid}: callouts.json not built yet - skipping checksum")
        return

    # Per-key checksum. resolvedKey wins when the drawing and legend disagree.
    tally: dict[str, int] = {}
    for c in callouts:
        key = c.get("resolvedKey", c["key"])
        tally[key] = tally.get(key, 0) + c["count"]

    drawn_total = sum(c["count"] for c in callouts)
    print(f"  drawing: {len(callouts)} callouts, {drawn_total} plants")

    # A declared discrepancy is a gap we looked for, could not resolve, and wrote
    # down. It downgrades to a warning so the gate still fails on anything new.
    declared = {d["key"]: d for d in sheet.get("discrepancies", [])}

    bad = 0
    for key in sorted(set(by_key) | set(tally)):
        want = by_key[key]["qty"] if key in by_key else None
        got = tally.get(key, 0)
        if want is None:
            errors.append(f"{sid}: callouts use key '{key}' that is not in the legend")
            bad += 1
        elif want != got:
            d = declared.get(key)
            if d and d["legendQty"] == want and d["drawnQty"] == got:
                warnings.append(f"{sid}: key {key} is a known, recorded gap - "
                                f"legend {want}, drawing {got}")
            else:
                errors.append(f"{sid}: key {key} ({by_key[key]['common'] or by_key[key]['botanical']}) "
                              f"- legend says {want}, callouts total {got}")
                bad += 1
    if not bad:
        print(f"  per-key checksum: {len(by_key)} keys, "
              f"{len(declared)} recorded gap(s), no unexplained mismatch")

    gap = sum(d["legendQty"] - d["drawnQty"] for d in declared.values())
    if drawn_total + gap != legend_total:
        errors.append(f"{sid}: callouts total {drawn_total} (+{gap} recorded gap) "
                      f"but legend totals {legend_total}")
    else:
        print(f"  total checksum: {drawn_total} + {gap} recorded == {legend_total}")

    uncertain = [c["id"] for c in callouts if c.get("uncertain")]
    if uncertain:
        warnings.append(f"{sid}: {len(uncertain)} callout(s) flagged uncertain: "
                        f"{', '.join(uncertain)}")
    inferred = [c["id"] for c in callouts if c.get("inferred")]
    if inferred:
        warnings.append(f"{sid}: {len(inferred)} callout(s) carry an inferred key "
                        f"resolution: {', '.join(inferred)}")

    # Callouts must sit inside the sheet.
    for c in callouts:
        if not (0 <= c["x"] <= sheet["width"] and 0 <= c["y"] <= sheet["height"]):
            errors.append(f"{sid}: callout {c['id']} at ({c['x']},{c['y']}) is "
                          f"outside the {sheet['width']}x{sheet['height']} sheet")

    if zones is None:
        warnings.append(f"{sid}: zones.json not built yet - skipping zone checks")
        return

    ids = [z["id"] for z in zones]
    if len(set(ids)) != len(ids):
        errors.append(f"{sid}: duplicate zone ids")

    unassigned, multi = [], []
    for c in callouts:
        hits = [z["id"] for z in zones if point_in_poly(c["x"], c["y"], z["polygon"])]
        if not hits:
            unassigned.append(c["id"])
        elif len(hits) > 1:
            multi.append(f"{c['id']}->{'/'.join(hits)}")
    print(f"  zones: {len(zones)} areas")
    if unassigned:
        errors.append(f"{sid}: {len(unassigned)} callout(s) fall in no zone: "
                      f"{', '.join(unassigned)}")
    if multi:
        errors.append(f"{sid}: {len(multi)} callout(s) fall in overlapping zones: "
                      f"{', '.join(multi)}")
    if not unassigned and not multi:
        print(f"  every callout lands in exactly one zone")

    for z in zones:
        if len(z["polygon"]) < 3:
            errors.append(f"{sid}: zone {z['id']} has fewer than 3 points")
        for x, y in z["polygon"]:
            if not (0 <= x <= sheet["width"] and 0 <= y <= sheet["height"]):
                errors.append(f"{sid}: zone {z['id']} has a point outside the sheet")
                break


def check_key_scoping(sheets: list[dict], errors: list[str]) -> None:
    """Confirm the collisions that make per-sheet scoping mandatory still exist."""
    print("\n=== cross-sheet key scoping ===")
    tables = {}
    for s in sheets:
        plants = load(DATA / s["id"] / "plants.json")
        if plants:
            tables[s["id"]] = {p["key"]: p for p in plants}
    if len(tables) < 2:
        return

    (a, ta), (b, tb) = list(tables.items())[:2]
    shared = sorted(set(ta) & set(tb))
    differing = [k for k in shared
                 if ta[k]["botanical"] != tb[k]["botanical"]
                 or ta[k]["qty"] != tb[k]["qty"]
                 or ta[k]["size"] != tb[k]["size"]]
    print(f"  {len(shared)} keys appear on both sheets; {len(differing)} of them "
          f"mean something different")
    for k in differing:
        if ta[k]["botanical"] != tb[k]["botanical"]:
            print(f"    {k}: {a} = {ta[k]['botanical']}  |  {b} = {tb[k]['botanical']}")
    if not differing:
        errors.append("expected colliding keys between sheets but found none - "
                      "check that both legends were transcribed independently")


def main() -> int:
    sheets = load(DATA / "sheets.json")
    errors: list[str] = []
    warnings: list[str] = []

    for sheet in sheets:
        check_sheet(sheet, errors, warnings)
    check_key_scoping(sheets, errors)

    print()
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"FAIL  {e}")
    if errors:
        print(f"\n{len(errors)} error(s)")
        return 1
    print(f"\nAll checks passed" + (f" ({len(warnings)} warning(s))" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
