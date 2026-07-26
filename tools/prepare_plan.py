#!/usr/bin/env python3
"""Rectify a phone photo of a paper blueprint into a flat, cropped plan image.

The photos were taken of paper lying on carpet: skewed by perspective, rotated,
and surrounded by background. This detects the sheet, warps it flat, cleans up
contrast, and emits the web-ready rasters.

Every coordinate used elsewhere in this project (zone polygons, callout markers,
SVG viewBox) lives in the rectified pixel space this script defines, so the
output dimensions are recorded into data/sheets.json and must stay stable.

Usage:
    python3 tools/prepare_plan.py --sheet sheet-03-front
    python3 tools/prepare_plan.py --sheet sheet-04-back --rotate 180
    python3 tools/prepare_plan.py --sheet X --corners "x1,y1 x2,y2 x3,y3 x4,y4"
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "images" / "source"
WIDTHS = (4096, 2048, 1024)


def order_quad(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype("float32")
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        dtype="float32",
    )


def detect_sheet(img: np.ndarray, debug_path: pathlib.Path | None = None) -> np.ndarray:
    """Find the paper's four corners.

    Brightness alone does not separate aged paper from tan carpet (Otsu grabs the
    whole frame). Saturation does: the carpet is a saturated tan (S~46-69) while
    the paper is near-neutral (S~23-29). Combining low-saturation AND high-value
    isolates the sheet reliably.
    """
    h, w = img.shape[:2]
    scale = 1000.0 / max(h, w)
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    hsv = cv2.cvtColor(cv2.GaussianBlur(small, (9, 9), 0), cv2.COLOR_BGR2HSV)
    sat, val = hsv[..., 1], hsv[..., 2]
    # Score high where the pixel is bright and neutral; the carpet scores low.
    score = cv2.subtract(val, cv2.multiply(sat, 1.6, dtype=cv2.CV_8U))
    _, mask = cv2.threshold(score, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Close over the printed line work so the sheet reads as one solid blob.
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise SystemExit("no contours found — pass --corners manually")
    biggest = max(contours, key=cv2.contourArea)
    frac = cv2.contourArea(biggest) / (small.shape[0] * small.shape[1])
    print(f"  sheet blob covers {frac:.1%} of the frame")

    # Try a 4-gon fit; fall back to the min-area rotated rect if the outline is
    # ragged (folded corners, a curled edge).
    quad = None
    for eps in (0.02, 0.03, 0.04, 0.05, 0.01):
        approx = cv2.approxPolyDP(biggest, eps * cv2.arcLength(biggest, True), True)
        if len(approx) == 4:
            quad = approx.astype("float32")
            print(f"  4-corner fit at eps={eps}")
            break
    if quad is None:
        quad = cv2.boxPoints(cv2.minAreaRect(biggest)).astype("float32")
        print("  no clean 4-gon; using min-area rotated rect")

    if debug_path is not None:
        dbg = small.copy()
        cv2.drawContours(dbg, [quad.astype(int)], -1, (0, 0, 255), 4)
        for i, (x, y) in enumerate(order_quad(quad)):
            cv2.circle(dbg, (int(x), int(y)), 12, (255, 0, 0), -1)
            cv2.putText(dbg, str(i), (int(x) + 14, int(y)), cv2.FONT_HERSHEY_SIMPLEX,
                        1.0, (255, 0, 0), 3)
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_path), dbg)

    return order_quad(quad) / scale


def warp(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = quad
    width = int(round(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))))
    height = int(round(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))))
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
                   dtype="float32")
    m = cv2.getPerspectiveTransform(quad, dst)
    return cv2.warpPerspective(img, m, (width, height), flags=cv2.INTER_CUBIC)


def trim_background(img: np.ndarray, pad: int = 4) -> np.ndarray:
    """Trim residual carpet left around the sheet after warping.

    Uses the same neutral-and-bright test as detect_sheet, then crops to the
    bounding box of the paper. Deliberately does not crop to the printed border
    rule: on these sheets the title block (scale, date, sheet number) sits
    outside that rule and would be lost.
    """
    h, w = img.shape[:2]
    hsv = cv2.cvtColor(cv2.GaussianBlur(img, (9, 9), 0), cv2.COLOR_BGR2HSV)
    score = cv2.subtract(hsv[..., 2], cv2.multiply(hsv[..., 1], 1.6, dtype=cv2.CV_8U))
    _, mask = cv2.threshold(score, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # A row/column is paper if most of it reads as paper.
    rows = mask.mean(axis=1) / 255 > 0.5
    cols = mask.mean(axis=0) / 255 > 0.5
    if not rows.any() or not cols.any():
        print("  background trim found no paper rows/cols — keeping full sheet")
        return img

    t, b = int(np.argmax(rows)), h - int(np.argmax(rows[::-1]))
    l, r = int(np.argmax(cols)), w - int(np.argmax(cols[::-1]))
    t, b = max(0, t + pad), min(h, b - pad)
    l, r = max(0, l + pad), min(w, r - pad)

    if b - t < h * 0.6 or r - l < w * 0.6:
        print("  background trim looked too aggressive — keeping full sheet")
        return img
    print(f"  trimmed background: {w}x{h} -> {r - l}x{b - t}")
    return img[t:b, l:r]


def enhance(img: np.ndarray) -> np.ndarray:
    """Even out the photographic lighting and lift the line work off the paper."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    # Divide out the low-frequency illumination gradient (shadow across the page).
    bg = cv2.GaussianBlur(l, (0, 0), sigmaX=l.shape[1] / 20)
    l = cv2.divide(l, bg, scale=192)
    l = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(12, 12)).apply(l)
    out = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    # Mild desaturation: the paper is aged and yellow-cast, the ink is blue-black.
    hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] *= 0.35
    return cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True, help="sheet id, e.g. sheet-03-front")
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--corners", help='manual quad: "x1,y1 x2,y2 x3,y3 x4,y4"')
    ap.add_argument("--inset", type=float, default=0.0,
                    help="trim this fraction off each edge after warping")
    ap.add_argument("--no-trim", action="store_true",
                    help="keep the carpet background around the warped sheet")
    args = ap.parse_args()

    src = SRC_DIR / f"{args.sheet}.jpeg"
    if not src.exists():
        raise SystemExit(f"missing source photo: {src}")

    img = cv2.imread(str(src))
    print(f"{args.sheet}: source {img.shape[1]}x{img.shape[0]}")

    if args.rotate:
        img = cv2.rotate(img, {90: cv2.ROTATE_90_CLOCKWISE,
                               180: cv2.ROTATE_180,
                               270: cv2.ROTATE_90_COUNTERCLOCKWISE}[args.rotate])
        print(f"  rotated {args.rotate}° -> {img.shape[1]}x{img.shape[0]}")

    out_dir = ROOT / "images" / args.sheet
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.corners:
        quad = order_quad(np.array(
            [[float(v) for v in p.split(",")] for p in args.corners.split()],
            dtype="float32"))
        print(f"  using manual corners:\n{quad}")
    else:
        quad = detect_sheet(img, out_dir / "_debug-detect.jpg")

    flat = warp(img, quad)
    print(f"  warped to {flat.shape[1]}x{flat.shape[0]}")

    if args.inset:
        h, w = flat.shape[:2]
        dx, dy = int(w * args.inset), int(h * args.inset)
        flat = flat[dy:h - dy, dx:w - dx]
        print(f"  inset {args.inset:.1%} -> {flat.shape[1]}x{flat.shape[0]}")

    if not args.no_trim:
        flat = trim_background(flat)

    flat = enhance(flat)

    base_w, base_h = flat.shape[1], flat.shape[0]

    # Always emit the native width as the largest variant. Naming a file
    # plan-4096 when the sheet is only 4020 px wide makes the browser pick a
    # candidate that does not exist, and the plan silently fails to render.
    targets = sorted({w for w in WIDTHS if w < base_w} | {base_w}, reverse=True)
    variants = []
    for target in targets:
        scale = target / base_w
        resized = cv2.resize(flat, (target, int(round(base_h * scale))),
                             interpolation=cv2.INTER_AREA)
        path = out_dir / f"plan-{target}.webp"
        cv2.imwrite(str(path), resized, [cv2.IMWRITE_WEBP_QUALITY, 88])
        variants.append(target)
        print(f"  wrote {path.name} {resized.shape[1]}x{resized.shape[0]} "
              f"({path.stat().st_size / 1024:.0f} KB)")

    # JPEG fallback for anything without WebP support.
    fb_scale = min(1.0, 2048 / base_w)
    fb = cv2.resize(flat, (int(base_w * fb_scale), int(base_h * fb_scale)),
                    interpolation=cv2.INTER_AREA)
    fb_path = out_dir / "plan.jpg"
    cv2.imwrite(str(fb_path), fb, [cv2.IMWRITE_JPEG_QUALITY, 84])
    print(f"  wrote {fb_path.name} ({fb_path.stat().st_size / 1024:.0f} KB)")

    # Full-resolution working copy for callout detection (not committed).
    work = out_dir / "_work-full.png"
    cv2.imwrite(str(work), flat)
    print(f"  wrote {work.name} (working copy for detection)")

    dims_path = out_dir / "_dims.json"
    dims_path.write_text(json.dumps(
        {"width": base_w, "height": base_h, "variants": sorted(variants)}, indent=2))
    print(f"  rectified space: {base_w} x {base_h}")
    print(f"  copy into data/sheets.json:  \"width\": {base_w}, \"height\": {base_h}, "
          f"\"variants\": {sorted(variants)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
