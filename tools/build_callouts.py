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
}

# Callouts the detector missed, located by hand after the checksum flagged a
# per-key shortfall. Coordinates are rectified-image pixels.
EXTRA: dict[str, list[dict]] = {
    "sheet-03-front": [
        {"key": "RF", "count": 4, "x": 255, "y": 863,
         "note": "Missed by shape detection - it sits alone at the far west edge "
                 "of the sheet. Found by chasing the RF shortfall in the checksum."},
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
            "id": f"f{len(out) + 1:03d}",
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
        rec = {"id": f"f{len(out) + 1:03d}", "bbox": None, "candidate": None}
        rec.update(extra)
        out.append(rec)

    out.sort(key=lambda r: (r["y"], r["x"]))
    for i, rec in enumerate(out, 1):
        rec["id"] = f"f{i:03d}"

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
