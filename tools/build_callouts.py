#!/usr/bin/env python3
"""Turn detected candidates plus hand-read keys into the final callouts.json.

The READINGS table below is the transcription: each entry maps a candidate index
from _callout-candidates.json to the key and count read off the contact sheets.
Candidates not listed were false positives (square utility boxes, label text,
shrub outlines) and are dropped. EXTRA holds real callouts the detector missed,
found by chasing per-key shortfalls in the legend checksum.

Keeping the transcription here rather than hand-editing JSON means the ids,
coordinates and bounding boxes always come straight from the detector.

Usage:  python3 tools/build_callouts.py --sheet sheet-03-front
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# candidate index (1-based, as labelled on the contact sheets) -> "KEY/COUNT"
READINGS: dict[str, dict[int, str]] = {
    "sheet-03-front": {
        1: "OF/1", 2: "PW/5", 3: "HH/1", 6: "DA/1", 7: "DB/2", 8: "MA/10",
        9: "AA/1", 10: "GI/4", 11: "LS/1", 13: "PW/1", 14: "PM/1", 15: "RC/1",
        16: "GS/1", 17: "PM/1", 18: "AP/3", 25: "AB/1", 29: "TJ/2", 30: "AA/5",
        31: "MP/3", 32: "RC/1", 33: "AP/1", 34: "LS/2", 35: "AP/3", 36: "CO/4",
        37: "LN/3", 38: "CP/4", 40: "BT/3", 41: "MA/4", 42: "AB/1", 43: "AP/3",
        44: "PW/1", 45: "CC/1", 47: "ND/1", 48: "HM/6", 49: "LM/4", 50: "MA/12",
        51: "AP/3", 52: "PS/1", 53: "BT/3", 54: "AH/1", 55: "LN/5", 56: "ND/1",
        57: "GN/5", 58: "ND/8", 59: "AA/1", 60: "RC/1", 61: "AU/1", 62: "GS/1",
        63: "AH/1", 64: "GN/2", 65: "DB/1", 67: "XC/1", 68: "HA/11", 69: "DB/1",
        71: "AA/2", 72: "HH/1", 75: "LN/3", 76: "GI/6", 77: "ND/3", 78: "PH/1",
        79: "OD/4", 80: "MF/5", 81: "HM/1", 82: "AH/1", 83: "ND/4", 84: "BA/9",
        85: "OD/2", 86: "HM/3", 87: "XC/1", 88: "RO/8", 89: "CE/1", 90: "PH/1",
        91: "RO/1", 92: "MF/1", 93: "BA/5", 94: "LM/9", 95: "CE/2", 96: "PT/8",
        97: "PH/1", 98: "PV/5", 99: "MS/1", 100: "HM/5", 101: "PW/1",
        102: "AA/3", 104: "CE/1", 105: "LN/2", 106: "AA/9", 107: "BA/3",
        108: "CP/3", 110: "LM/14",
    },
    "sheet-04-back": {
        1: "HA/1", 2: "PV/4", 3: "CC/1", 4: "AA/7", 5: "LC/8", 6: "AG/5", 7: "TR/1",
        8: "PT/7", 9: "DA/3", 10: "PV/9", 11: "AG/1", 12: "AB/1", 13: "RF/15",
        15: "HV/1", 16: "AA/23", 17: "DO/3", 18: "LC/3", 19: "CC/1", 20: "LS/3",
        21: "PJ/1", 22: "RC/4", 23: "AA/10", 24: "DO/2", 25: "CM/3", 27: "AH/1",
        28: "RC/6", 29: "PF/3", 30: "PW/6", 32: "AA/3", 33: "LI/1", 35: "OF/2",
        36: "OF/7", 37: "TJ/12", 38: "AH/1", 40: "PC/1", 41: "DB/2", 43: "R/3",
        47: "MA/5", 48: "R/6", 49: "CT/7", 50: "TJ/11", 51: "MA/3", 52: "AG/1",
        53: "OD/4", 54: "RB/6", 57: "CL/2", 58: "DB/2", 59: "DB/1", 60: "OD/2",
        63: "OF/1", 64: "BT/1", 65: "AA/1", 69: "IS/11", 70: "LS/2", 71: "LT/1",
        72: "PJ/2", 73: "RB/3", 74: "R/1", 75: "LS/1", 81: "RC/3",
    },
}

# Callouts the detector missed, located by hand after the checksum flagged a
# per-key shortfall. Coordinates are rectified-image pixels.
EXTRA: dict[str, list[dict]] = {
    "sheet-03-front": [
        {"key": "RF", "count": 4, "x": 255, "y": 863,
         "note": "Missed by shape detection - it sits alone at the far west edge "
                 "of the sheet. Found by chasing the RF shortfall in the checksum."},
    ],
    "sheet-04-back": [
        # A column in the blank west margin, below the detector's reach.
        {"key": "AA", "count": 1, "x": 292, "y": 2010},
        {"key": "CC", "count": 1, "x": 298, "y": 2074},
        {"key": "MY", "count": 14, "x": 357, "y": 2135},
        # Two more tucked against the east edge, right up beside the legend block.
        {"key": "TJ", "count": 7, "x": 2676, "y": 2093},
        {"key": "BS", "count": 1, "x": 2682, "y": 2152},
    ],
}

# Where the drawing and the legend genuinely disagree. Recorded rather than
# silently corrected.
RESOLUTIONS: dict[str, dict[int, dict]] = {
    "sheet-03-front": {
        8: {"resolvedKey": "MY", "inferred": True},
        50: {"resolvedKey": "MY", "inferred": True},
    },
}

AMBIGUITY_NOTE = (
    "The drawing labels every Myrsine africana callout 'MA', but the legend "
    "splits the species into MA (4 plants, 5 gallon) and MY (22 plants, "
    "1 gallon). The three MA callouts total 26, which is exactly 4 + 22. The "
    "MA/4 callout is taken as the 5-gallon group and the MA/10 and MA/12 "
    "callouts as the 22 one-gallon plants. That split is inferred, not stated "
    "on the sheet."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    args = ap.parse_args()

    if args.sheet not in READINGS:
        raise SystemExit(f"no readings recorded for {args.sheet}")

    data_dir = ROOT / "data" / args.sheet
    cands = json.loads((data_dir / "_callout-candidates.json").read_text())
    readings = READINGS[args.sheet]
    resolutions = RESOLUTIONS.get(args.sheet, {})

    out = []
    for idx, spec in sorted(readings.items()):
        if not 1 <= idx <= len(cands):
            raise SystemExit(f"reading #{idx} is outside the candidate list")
        c = cands[idx - 1]
        key, count = spec.split("/")
        rec = {
            "id": None,
            "key": key,
            "count": int(count),
            "x": c["x"],
            "y": c["y"],
            "bbox": c["bbox"],
            "candidate": idx,
        }
        if idx in resolutions:
            rec.update(resolutions[idx])
            rec["ambiguityNote"] = AMBIGUITY_NOTE
        out.append(rec)

    for extra in EXTRA.get(args.sheet, []):
        rec = {"id": None, "bbox": None, "candidate": None}
        rec.update(extra)
        out.append(rec)

    out.sort(key=lambda r: (r["y"], r["x"]))
    prefix = "f" if args.sheet.endswith("front") else "b"
    for i, rec in enumerate(out, 1):
        rec["id"] = f"{prefix}{i:03d}"

    path = data_dir / "callouts.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    total = sum(r["count"] for r in out)
    print(f"{args.sheet}: {len(out)} callouts, {total} plants -> "
          f"{path.relative_to(ROOT)}")
    print(f"  dropped {len(cands) - len(readings)} false-positive candidates")
    print(f"  added {len(EXTRA.get(args.sheet, []))} hand-located callouts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
