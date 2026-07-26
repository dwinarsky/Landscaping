#!/usr/bin/env python3
"""Render detected callouts as magnified contact sheets for reading by eye.

detect_callouts.py finds *where* the hexagons are; it cannot read them. No OCR
engine is installed in this environment, and the stylized hand-lettering on a
2001 blueprint photographed on a carpet defeats the ones that are. So the keys
and counts are read off these contact sheets and typed into callouts.json, then
checked against the legend quantities by validate.py.

Each cell shows one candidate blown up with its index, so a reading can be
mapped back to a candidate id unambiguously.

Usage:
    python3 tools/contact_sheet.py --sheet sheet-03-front
    python3 tools/contact_sheet.py --sheet sheet-03-front --only 45-60
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent


def parse_only(spec: str | None, n: int) -> list[int]:
    if not spec:
        return list(range(n))
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a) - 1, int(b)))
        else:
            out.append(int(part) - 1)
    return [i for i in out if 0 <= i < n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--rows", type=int, default=4)
    ap.add_argument("--cell", type=int, default=210, help="cell size in px")
    ap.add_argument("--pad", type=int, default=14,
                    help="extra source px around each hexagon")
    ap.add_argument("--only", help="1-based index list/ranges, e.g. 1-20,35")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    cand_path = ROOT / "data" / args.sheet / "_callout-candidates.json"
    cands = json.loads(cand_path.read_text())
    img = cv2.imread(str(ROOT / "images" / args.sheet / "_work-full.png"))
    if img is None:
        raise SystemExit(f"run prepare_plan.py for {args.sheet} first")

    idxs = parse_only(args.only, len(cands))
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else (
        ROOT / "images" / args.sheet / "_contact")
    out_dir.mkdir(parents=True, exist_ok=True)

    per = args.cols * args.rows
    cell, label_h = args.cell, 30
    sheets = 0
    for start in range(0, len(idxs), per):
        chunk = idxs[start:start + per]
        canvas = np.full((args.rows * (cell + label_h), args.cols * cell, 3),
                         255, np.uint8)
        for slot, i in enumerate(chunk):
            c = cands[i]
            x, y, w, h = c["bbox"]
            x0, y0 = max(0, x - args.pad), max(0, y - args.pad)
            x1 = min(img.shape[1], x + w + args.pad)
            y1 = min(img.shape[0], y + h + args.pad)
            crop = img[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            scale = cell / max(crop.shape[0], crop.shape[1])
            crop = cv2.resize(crop, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC)
            # Push contrast hard: these are read by eye, not by an algorithm.
            crop = cv2.normalize(crop, None, 0, 255, cv2.NORM_MINMAX)
            r, cc = divmod(slot, args.cols)
            oy = r * (cell + label_h) + label_h
            ox = cc * cell
            canvas[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
            cv2.putText(canvas, f"#{i + 1}", (ox + 6, oy - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 200), 2, cv2.LINE_AA)
        n = start // per + 1
        path = out_dir / f"contact-{n:02d}.png"
        cv2.imwrite(str(path), canvas)
        print(f"  wrote {path.relative_to(ROOT)} "
              f"(#{chunk[0] + 1}-#{chunk[-1] + 1})")
        sheets += 1
    print(f"{sheets} contact sheet(s) for {len(idxs)} candidates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
