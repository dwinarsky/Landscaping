#!/usr/bin/env python3
"""Locate the hexagonal plant callouts on a rectified plan sheet.

Each callout is a flattened hexagon roughly 46x46 px at full rectified
resolution: a flat top edge about two thirds of the width, points at left and
right mid-height, a full-width horizontal divider, and a flat bottom edge. The
two-letter plant key sits above the divider and the count below it.

Finding these by contour analysis fails because every hexagon is fused to its
leader line, so the outline is never an isolated closed contour. Instead:

  1. propose candidates by template-matching a synthetic hexagon outline, with
     the interior masked out so the lettering inside does not hurt the score;
  2. verify each candidate structurally by looking for the three horizontal
     rules at the expected offsets and widths;
  3. suppress overlapping detections.

Reading the key and count is a separate step (contact_sheet.py) done by eye:
no OCR engine is available here and the stylized lettering defeats the ones
that are.

Usage:
    python3 tools/detect_callouts.py --sheet sheet-03-front --region 0,150,2520,2665
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent


def hex_template(w: int, h: int, stroke: int = 3) -> np.ndarray:
    t = np.zeros((h, w), np.uint8)
    fw = int(round(w * 0.66))
    x0 = (w - fw) // 2
    mid = h // 2
    pts = np.array([[x0, 0], [x0 + fw, 0], [w - 1, mid],
                    [x0 + fw, h - 1], [x0, h - 1], [0, mid]], np.int32)
    cv2.polylines(t, [pts], True, 255, stroke)
    cv2.line(t, (1, mid), (w - 2, mid), 255, stroke)
    return t


def ink_mask(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV, 25, 10)


def longest_run(row: np.ndarray, gap: int = 3) -> int:
    """Longest horizontal run of ink, tolerating small gaps."""
    best = run = 0
    since = gap + 1
    for v in row:
        if v:
            if since <= gap:
                run += since
            run += 1
            since = 0
        else:
            since += 1
            if since > gap:
                best = max(best, run)
                run = 0
    return max(best, run)


def verify(patch: np.ndarray, w: int, h: int) -> float | None:
    """Score a candidate on the three horizontal rules a callout must have.

    Returns None when the structure is absent. The band searches are generous
    because the drawing is hand-inked and the photo was slightly non-planar.
    """
    if patch.shape[0] < h or patch.shape[1] < w:
        return None
    ink = patch > 0

    def band_best(y0: int, y1: int) -> tuple[int, int]:
        y0, y1 = max(0, y0), min(h, y1)
        if y1 <= y0:
            return 0, 0
        runs = [longest_run(ink[y]) for y in range(y0, y1)]
        i = int(np.argmax(runs))
        return runs[i], y0 + i

    mid = h // 2
    top_run, _ = band_best(0, max(1, int(h * 0.16)))
    div_run, _ = band_best(mid - int(h * 0.10), mid + int(h * 0.10) + 1)
    bot_run, _ = band_best(h - int(h * 0.16), h)

    # Top and bottom edges are the flat two-thirds; the divider spans the width.
    if not (0.45 * w <= top_run <= 0.92 * w):
        return None
    if not (0.45 * w <= bot_run <= 0.92 * w):
        return None
    if div_run < 0.78 * w:
        return None
    # The two chambers must hold *some* lettering but not be solid ink.
    upper = ink[int(h * 0.18):mid - 2, int(w * 0.2):int(w * 0.8)].mean()
    lower = ink[mid + 2:int(h * 0.82), int(w * 0.2):int(w * 0.8)].mean()
    if not (0.03 <= upper <= 0.75) or not (0.03 <= lower <= 0.75):
        return None
    return (top_run + bot_run) / (2 * w) + div_run / w


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--region", help="x,y,w,h to restrict the search to")
    ap.add_argument("--size", type=int, default=46, help="hexagon size in px")
    ap.add_argument("--threshold", type=float, default=0.58)
    ap.add_argument("--min-dist", type=int, default=24)
    args = ap.parse_args()

    img_dir = ROOT / "images" / args.sheet
    img = cv2.imread(str(img_dir / "_work-full.png"))
    if img is None:
        raise SystemExit(f"run prepare_plan.py for {args.sheet} first")
    print(f"{args.sheet}: {img.shape[1]}x{img.shape[0]}")

    ox = oy = 0
    view = img
    if args.region:
        ox, oy, rw, rh = (int(v) for v in args.region.split(","))
        view = img[oy:oy + rh, ox:ox + rw]
        print(f"  searching region {ox},{oy} {rw}x{rh}")

    ink = ink_mask(view)
    n = args.size
    tpl = hex_template(n, n).astype(np.float32)
    mask = cv2.dilate(hex_template(n, n, 5), np.ones((3, 3), np.uint8)).astype(np.float32)
    res = np.nan_to_num(cv2.matchTemplate(ink.astype(np.float32), tpl,
                                          cv2.TM_CCORR_NORMED, mask=mask))
    ys, xs = np.where(res >= args.threshold)
    print(f"  {len(ys)} raw template peaks at >= {args.threshold}")

    scored = []
    for y, x in zip(ys, xs):
        s = verify(ink[y:y + n, x:x + n], n, n)
        if s is not None:
            scored.append((s * float(res[y, x]), int(x), int(y)))
    print(f"  {len(scored)} passed the three-rule structural check")

    kept: list[dict] = []
    for s, x, y in sorted(scored, key=lambda t: -t[0]):
        cx, cy = x + n // 2, y + n // 2
        if any((cx - k["x"]) ** 2 + (cy - k["y"]) ** 2 <= args.min_dist ** 2
               for k in kept):
            continue
        kept.append({"x": cx, "y": cy, "bbox": [x, y, n, n], "score": round(s, 4)})
    print(f"  {len(kept)} after non-maximum suppression")

    kept.sort(key=lambda d: (d["y"], d["x"]))
    prefix = args.sheet.split("-")[1]
    for i, c in enumerate(kept, 1):
        c["id"] = f"{prefix}{i:03d}"
        c["x"] += ox
        c["y"] += oy
        c["bbox"][0] += ox
        c["bbox"][1] += oy

    out = ROOT / "data" / args.sheet / "_callout-candidates.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(kept, indent=1))
    print(f"  wrote {out.relative_to(ROOT)}")

    overlay = img.copy()
    for c in kept:
        x, y, w, h = c["bbox"]
        cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cv2.putText(overlay, c["id"][-3:], (x, y - 4), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 0, 0), 1, cv2.LINE_AA)
    dbg = img_dir / "_debug-callouts.jpg"
    cv2.imwrite(str(dbg), overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(f"  wrote {dbg.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
