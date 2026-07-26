#!/usr/bin/env python3
"""Render a zoomed crop of the plan for each garden zone.

This is the "here is the plan for this spot" visual in the zone pop-up: the
drawing itself, framed on the area you tapped, so the beds and callouts are
legible without pinch-zooming around.

Usage:  python3 tools/crop_zones.py --sheet sheet-03-front
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--pad", type=int, default=40, help="padding in source px")
    ap.add_argument("--max-dim", type=int, default=1100)
    ap.add_argument("--quality", type=int, default=86)
    args = ap.parse_args()

    zones = json.loads((ROOT / "data" / args.sheet / "zones.json").read_text())
    img = cv2.imread(str(ROOT / "images" / args.sheet / "_work-full.png"))
    if img is None:
        raise SystemExit(f"run prepare_plan.py for {args.sheet} first")
    h, w = img.shape[:2]

    out_dir = ROOT / "images" / args.sheet / "zones"
    out_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for z in zones:
        # Some zones' callouts sit out in the sheet margin next to the legend
        # table, so the polygon's bounding box frames label text rather than the
        # planting. cropRect lets those zones point at the bed instead.
        if "cropRect" in z:
            r = z["cropRect"]
            x0, y0 = max(0, r["x"]), max(0, r["y"])
            x1, y1 = min(w, r["x"] + r["width"]), min(h, r["y"] + r["height"])
        else:
            xs = [p[0] for p in z["polygon"]]
            ys = [p[1] for p in z["polygon"]]
            x0 = max(0, min(xs) - args.pad)
            y0 = max(0, min(ys) - args.pad)
            x1 = min(w, max(xs) + args.pad)
            y1 = min(h, max(ys) + args.pad)
        crop = img[y0:y1, x0:x1]
        if crop.size == 0:
            print(f"  !! {z['id']}: empty crop")
            continue
        scale = min(1.0, args.max_dim / max(crop.shape[0], crop.shape[1]))
        if scale < 1.0:
            crop = cv2.resize(crop, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_AREA)
        path = out_dir / f"{z['id']}.webp"
        cv2.imwrite(str(path), crop, [cv2.IMWRITE_WEBP_QUALITY, args.quality])
        kb = path.stat().st_size / 1024
        total += kb
        print(f"  {z['id']:<20} {crop.shape[1]}x{crop.shape[0]}  {kb:5.0f} KB")

    print(f"{len(zones)} zone crops, {total / 1024:.1f} MB total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
