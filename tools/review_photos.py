#!/usr/bin/env python3
"""Build contact sheets of candidate photos so a human can pick the good one.

Keyword scoring gets most species right, but Wikimedia titles lie by omission:
a picture captioned only "Daphne odora" can be a plant label on a stake, and
"Podocarpus potted plants wholesale" is a nursery yard. The only reliable filter
for "does this show me what the plant looks like" is looking at it.

This downloads thumbnails of every candidate for a species and tiles them with
index numbers. Pick the good one by eye and record it in the PICKS table in
fetch_plant_photos.py, then re-run that with --force.

Usage:
    python3 tools/review_photos.py --species "Agapanthus africanus" "Daphne odora"
    python3 tools/review_photos.py --from-credits          # every species
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import re
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fetch_plant_photos as F                              # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "images" / "plants" / "_review"


def thumb(url: str, size: int) -> np.ndarray | None:
    try:
        im = Image.open(io.BytesIO(F.fetch(url, timeout=60))).convert("RGB")
    except Exception as e:                                   # noqa: BLE001
        print(f"        thumb failed: {e}")
        return None
    im.thumbnail((size, size))
    canvas = Image.new("RGB", (size, size), (245, 245, 247))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    return cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)


def combined(names, args, index) -> int:
    """One row per species, several species per sheet.

    Reviewing these by eye is the expensive part, and an image costs the same
    whether it holds one species or four. Packing rows cuts the number of
    sheets to look at by about four times.
    """
    cell, lab, per_row = args.cell, 26, args.limit
    rows_per_sheet = args.rows
    sheet, batch = 1, []

    def flush(batch, sheet):
        h = len(batch) * (cell + lab)
        canvas = np.full((h, per_row * cell, 3), 255, np.uint8)
        for r, (name, pool) in enumerate(batch):
            y = r * (cell + lab) + lab
            cv2.putText(canvas, name, (4, y - 8), cv2.FONT_HERSHEY_SIMPLEX,
                        0.52, (0, 0, 190), 2, cv2.LINE_AA)
            for i, c in enumerate(pool[:per_row]):
                t = thumb(c["url"], cell)
                if t is None:
                    continue
                canvas[y:y + cell, i * cell:(i + 1) * cell] = t
                cv2.putText(canvas, f"#{i}", (i * cell + 6, y + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 220), 2, cv2.LINE_AA)
        path = OUT / f"_combined-{sheet:02d}.png"
        cv2.imwrite(str(path), canvas)
        print(f"  -> {path.relative_to(ROOT)} ({len(batch)} species)")

    for name in names:
        genus = name.split()[0].lower()
        print(f"  {name}")
        pool = F.gather(name, genus)[:per_row]
        if not pool:
            print("      no candidates")
            continue
        index[name] = [{"i": i, "title": c["title"], "licence": c["licence"]}
                       for i, c in enumerate(pool)]
        batch.append((name, pool))
        if len(batch) == rows_per_sheet:
            flush(batch, sheet)
            batch, sheet = [], sheet + 1
    if batch:
        flush(batch, sheet)

    path = OUT / "_index.json"
    prev = json.loads(path.read_text()) if path.exists() else {}
    prev.update(index)
    path.write_text(json.dumps(prev, indent=1) + "\n")
    print(f"\n{len(index)} species reviewed")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combined", action="store_true",
                    help="pack several species per sheet, one row each")
    ap.add_argument("--rows", type=int, default=4, help="species per combined sheet")
    ap.add_argument("--species", nargs="*", default=[])
    ap.add_argument("--from-credits", action="store_true")
    ap.add_argument("--limit", type=int, default=12, help="candidates per species")
    ap.add_argument("--cell", type=int, default=250)
    args = ap.parse_args()

    names = list(args.species)
    if args.from_credits:
        cred = json.loads((ROOT / "images" / "plants" / "CREDITS.json").read_text())
        names += sorted({F.strip_cultivar(v["botanical"]) or v["botanical"]
                         for v in cred.values()})

    OUT.mkdir(parents=True, exist_ok=True)
    index: dict[str, list[dict]] = {}

    if args.combined:
        return combined(names, args, index)

    for name in names:
        genus = name.split()[0].lower()
        print(f"  {name}")
        pool = F.gather(name, genus)[: args.limit]
        if not pool:
            print("      no candidates")
            continue

        cols = 4
        rows = (len(pool) + cols - 1) // cols
        cell, lab = args.cell, 30
        canvas = np.full((rows * (cell + lab), cols * cell, 3), 255, np.uint8)
        for i, c in enumerate(pool):
            t = thumb(c["url"], cell)
            if t is None:
                continue
            r, q = divmod(i, cols)
            y = r * (cell + lab) + lab
            canvas[y:y + cell, q * cell:(q + 1) * cell] = t
            cv2.putText(canvas, f"#{i}", (q * cell + 5, y - 9),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 200), 2, cv2.LINE_AA)
            cv2.putText(canvas, c["title"].replace("File:", "")[:34],
                        (q * cell + 42, y - 9), cv2.FONT_HERSHEY_SIMPLEX,
                        0.36, (90, 90, 90), 1, cv2.LINE_AA)

        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        path = OUT / f"{slug}.png"
        cv2.imwrite(str(path), canvas)
        index[name] = [{"i": i, "title": c["title"], "licence": c["licence"]}
                       for i, c in enumerate(pool)]
        print(f"      {len(pool)} candidates -> {path.relative_to(ROOT)}")

    (OUT / "_index.json").write_text(json.dumps(index, indent=1) + "\n")
    print(f"\n{len(index)} species reviewed; index at {(OUT / '_index.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
