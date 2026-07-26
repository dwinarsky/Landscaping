#!/usr/bin/env python3
"""Bundle the whole map into one self-contained HTML file.

A published Artifact runs under a strict CSP that blocks every external request,
so nothing can be fetched at runtime. This inlines the CSS, the ES modules, the
JSON and the images as data URIs, producing a single file that also happens to
work offline from a phone's downloads folder or over email.

Size is the constraint. Plan rasters use the 2048px variant, plant photos use
the 320px thumbnails, and zone crops are re-encoded smaller.

Usage:  python3 tools/build_artifact.py [--max-mb 4]
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import pathlib
import re
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

DATA_FILES = ["data/sheets.json", "data/meta.json", "data/site-legend.json",
              "images/plants/CREDITS.json"]
MODULES = ["js/util.js", "js/data.js", "js/viewer.js", "js/hotspots.js",
           "js/panel.js", "js/search.js", "js/editor.js", "js/app.js"]


def data_uri(path: pathlib.Path, raw: bytes | None = None) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    blob = raw if raw is not None else path.read_bytes()
    return f"data:{mime};base64," + base64.b64encode(blob).decode()


def shrink(path: pathlib.Path, max_w: int, quality: int) -> bytes:
    im = Image.open(path)
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-mb", type=float, default=4.0)
    ap.add_argument("--plan-width", type=int, default=2048)
    ap.add_argument("--photo-width", type=int, default=300)
    ap.add_argument("--zone-width", type=int, default=620)
    args = ap.parse_args()

    sheets = json.loads((ROOT / "data" / "sheets.json").read_text())

    # ---- data ------------------------------------------------------------
    payload: dict[str, object] = {}
    for rel in DATA_FILES:
        payload[rel] = json.loads((ROOT / rel).read_text())
    for s in sheets:
        for name in ("plants", "callouts", "zones"):
            rel = f"data/{s['id']}/{name}.json"
            p = ROOT / rel
            if not p.exists():
                continue
            body = json.loads(p.read_text())
            if name == "callouts":
                # bbox and candidate are provenance for the tooling; the running
                # map never reads them, and they are a third of the file.
                body = [{k: v for k, v in c.items()
                         if k not in ("bbox", "candidate")} for c in body]
            payload[rel] = body

    # ---- images ----------------------------------------------------------
    assets: dict[str, str] = {}
    budget = {"plan": 0, "zones": 0, "plants": 0}

    for s in sheets:
        # Ship exactly one raster per sheet and narrow the sheet's variant list
        # to match. Registering the same data URI under every variant name would
        # embed the whole image two extra times.
        src = ROOT / f"{s['plan']}-{args.plan_width}.webp"
        if not src.exists():
            src = ROOT / f"{s['plan']}-{max(s['variants'])}.webp"
        blob = shrink(src, args.plan_width, 76)
        assets[f"{s['plan']}-{args.plan_width}.webp"] = data_uri(pathlib.Path("plan.webp"), blob)
        budget["plan"] += len(blob)

    for s in payload["data/sheets.json"]:
        s["variants"] = [args.plan_width]

    for s in sheets:
        zone_dir = ROOT / "images" / s["id"] / "zones"
        for z in json.loads((ROOT / "data" / s["id"] / "zones.json").read_text()):
            f = zone_dir / f"{z['id']}.webp"
            if f.exists():
                blob = shrink(f, args.zone_width, 70)
                assets[f"images/{s['id']}/zones/{z['id']}.webp"] = data_uri(f, blob)
                budget["zones"] += len(blob)

    seen: set[str] = set()
    for s in sheets:
        for p in json.loads((ROOT / "data" / s["id"] / "plants.json").read_text()):
            slug = re.sub(r"[^a-z0-9]+", "-", p["botanical"].lower()).strip("-")
            if slug in seen:
                continue
            seen.add(slug)
            small = ROOT / "images" / "plants" / f"{slug}-sm.jpg"
            if not small.exists():
                continue
            blob = shrink(small, args.photo_width, 72)
            # Register the thumbnail only. asset() in data.js falls back from
            # the full-size path to this one, so embedding it twice is waste.
            assets[f"images/plants/{slug}-sm.jpg"] = data_uri(pathlib.Path("p.webp"), blob)
            budget["plants"] += len(blob)

    # ---- assemble --------------------------------------------------------
    html = (ROOT / "index.html").read_text()
    css = (ROOT / "css" / "app.css").read_text()

    # Concatenate the modules, stripping their cross-imports and export
    # keywords so they run as one classic script under the CSP.
    parts = []
    for rel in MODULES:
        src = (ROOT / rel).read_text()
        # Aliased imports would lose their local name when the import line is
        # stripped, leaving an undefined reference only in the bundle.
        alias = re.search(r"^\s*import\s+\{[^}]*\bas\b[^}]*\}", src, re.M)
        if alias:
            raise SystemExit(f"{rel}: aliased import breaks bundling -> {alias.group(0).strip()}")
        src = re.sub(r'^\s*import\s.*?from\s+["\'][^"\']+["\'];?\s*$', "", src, flags=re.M)
        src = re.sub(r"^export\s+", "", src, flags=re.M)
        src = re.sub(r"^\s*export\s*\{[^}]*\};?\s*$", "", src, flags=re.M)
        parts.append(f"/* ===== {rel} ===== */\n{src}")
    bundle = "\n".join(parts)

    head = (f"<script>window.__PLAN_DATA__={json.dumps(payload, separators=(',', ':'))};"
            f"window.__PLAN_ASSETS__={json.dumps(assets, separators=(',', ':'))};</script>")

    html = html.replace('<link rel="stylesheet" href="css/app.css">',
                        f"<style>\n{css}\n</style>")
    html = html.replace('<script type="module" src="js/app.js"></script>',
                        head + f"\n<script>\n{bundle}\n</script>")

    DIST.mkdir(exist_ok=True)
    out = DIST / "artifact.html"
    out.write_text(html)

    mb = out.stat().st_size / 1024 / 1024
    print(f"  plan rasters : {budget['plan'] / 1024:7.0f} KB")
    print(f"  zone crops   : {budget['zones'] / 1024:7.0f} KB")
    print(f"  plant photos : {budget['plants'] / 1024:7.0f} KB ({len(seen)} species)")
    print(f"  -> {out.relative_to(ROOT)}  {mb:.2f} MB")
    if mb > args.max_mb:
        print(f"  !! over the {args.max_mb} MB budget - lower --plan-width or --photo-width")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
