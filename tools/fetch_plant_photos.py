#!/usr/bin/env python3
"""Fetch one openly-licensed photo per species from Wikimedia Commons.

The blueprint tells you a plant is "Coleonema pulchrum 'Sunset Gold'". That is
not much use standing in the yard unless you know what it looks like, so each
plant card gets a real photograph.

Only images with a clear, redistributable licence are kept, and the licence,
author and source URL are recorded in CREDITS.json so the app can attribute
every photo - CC-BY and CC-BY-SA require it.

Cultivars often have no photo of their own on Commons. In that case this falls
back to the parent species and records that fact, so the app can say "photo
shows the species, not this cultivar" rather than implying a match it cannot
support. Anything with no usable result is reported and left without a photo;
a wrong plant is worse than no plant.

Usage:
    python3 tools/fetch_plant_photos.py                 # all sheets
    python3 tools/fetch_plant_photos.py --sheet sheet-03-front
    python3 tools/fetch_plant_photos.py --only AA,BA --force
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://commons.wikimedia.org/w/api.php"
UA = "PearsonResidenceLandscapeMap/1.0 (personal garden reference; contact via repo)"

OK_LICENCES = ("cc0", "cc-by", "cc-by-sa", "public domain", "pd-", "attribution")
BAD_LICENCES = ("nc", "nd", "fair use", "non-free")

LARGE, SMALL = 1024, 320


MIN_INTERVAL = 1.5      # seconds between any two outbound requests
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def fetch(url: str, timeout: int = 60) -> bytes:
    """GET with throttling and exponential backoff on rate limiting."""
    delay = 4.0
    for attempt in range(6):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 5:
                print(f"      rate limited ({e.code}), waiting {delay:.0f}s")
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < 5:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def api(params: dict) -> dict:
    params = {**params, "format": "json"}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    return json.loads(fetch(url, timeout=45).decode())


# The blueprint abbreviates species epithets ("Berberis thu. 'Crimson Pygmy'")
# and carries a few spelling slips. Expanding them is what makes a species
# search actually find the plant.
ABBREV = {
    "thu.": "thunbergii",
    "vio.": "violacea",
    "sco.": "scoparium",
    "par.": "parvifolium",
    "o.": "officinalis",
    "hyb.": "",
    "var.": "",
    "noatratum": "",
    "x": "",
    "X": "",
}

# Blueprint spelling -> accepted name, for the cases an abbreviation map cannot fix.
CORRECTIONS = {
    "phorium": "Phormium",
}

# Where even the corrected species name is not a Commons search term, say what to
# look for instead.
SEARCH_OVERRIDE = {
    "Rosa var. noatratum 'Flower Carpet'": "Rosa Flower Carpet",
    "Rosa 'Hybrid Tea'": "Hybrid tea rose",
    "Lagerstroemia X 'Natchez'": "Lagerstroemia indica Natchez",
    # Searching the bare genus "Phormium" returns New Zealand scenery, not the plant.
    "Phorium 'Gold Sword'": "Phormium tenax leaves",
    "Rosmarinus o. 'Collingwood Ingram'": "Rosmarinus officinalis flowers",
    "Rosmarinus o. 'Benenden Blue'": "Rosmarinus officinalis flowers",
}


def strip_cultivar(botanical: str) -> str:
    """'Berberis thu. 'Crimson Pygmy'' -> 'Berberis thunbergii'."""
    s = re.sub(r"'[^']*'", " ", botanical)
    s = re.sub(r'"[^"]*"', " ", s)
    words = []
    for w in s.split():
        w = ABBREV.get(w, w)
        w = CORRECTIONS.get(w.lower(), w)
        if w:
            words.append(w)
    return " ".join(words)


def search_images(term: str, limit: int = 12) -> list[str]:
    try:
        r = api({"action": "query", "list": "search", "srsearch": f'{term} filetype:bitmap',
                 "srnamespace": "6", "srlimit": str(limit)})
    except Exception as e:                                    # noqa: BLE001
        print(f"      search failed: {e}")
        return []
    return [h["title"] for h in r.get("query", {}).get("search", [])]


def image_info(titles: list[str]) -> dict:
    if not titles:
        return {}
    try:
        r = api({"action": "query", "titles": "|".join(titles), "prop": "imageinfo",
                 "iiprop": "url|size|extmetadata|mime", "iiurlwidth": str(LARGE)})
    except Exception as e:                                    # noqa: BLE001
        print(f"      imageinfo failed: {e}")
        return {}
    return r.get("query", {}).get("pages", {})


def licence_ok(meta: dict) -> tuple[bool, str]:
    short = (meta.get("LicenseShortName", {}).get("value") or "").strip()
    code = (meta.get("License", {}).get("value") or "").strip().lower()
    blob = f"{short} {code}".lower()
    if any(b in blob for b in BAD_LICENCES):
        return False, short or code
    if any(g in blob for g in OK_LICENCES):
        return True, short or code
    return False, short or code


def clean_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return " ".join(s.split())[:180]


def pick(term: str, genus: str | None = None) -> dict | None:
    """Best landscape-ish, decently sized, properly licensed image for a term.

    Requires the genus to appear in the file name. Without that guard a bare
    genus search happily returns scenery from where the plant grows - searching
    "Phormium" returns New Zealand lake views rather than the flax itself.
    """
    genus = (genus or term.split()[0]).lower()
    pages = image_info(search_images(term))
    best = None
    for page in pages.values():
        if genus not in page.get("title", "").lower():
            continue
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        if not (info.get("mime", "")).startswith("image/"):
            continue
        w, h = info.get("width", 0), info.get("height", 0)
        if w < 500 or h < 380:
            continue
        meta = info.get("extmetadata", {})
        ok, lic = licence_ok(meta)
        if not ok:
            continue
        ratio = w / h
        # Prefer landscape-ish framing, then bigger.
        score = (2.0 if 1.15 <= ratio <= 2.0 else 1.0) * min(w, 2600)
        if best is None or score > best["score"]:
            best = {
                "score": score,
                "title": page["title"],
                "url": info.get("thumburl") or info["url"],
                "descriptionurl": info.get("descriptionurl", ""),
                "licence": lic,
                "author": clean_html(meta.get("Artist", {}).get("value", "")) or "Unknown",
                "credit": clean_html(meta.get("Credit", {}).get("value", "")),
            }
    return best


def download(url: str) -> Image.Image:
    return Image.open(io.BytesIO(fetch(url, timeout=90))).convert("RGB")


def save(im: Image.Image, path: pathlib.Path, width: int) -> None:
    w, h = im.size
    if w > width:
        im = im.resize((width, max(1, round(h * width / w))), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=82, optimize=True, progressive=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", help="limit to one sheet id")
    ap.add_argument("--only", help="comma-separated plant keys")
    ap.add_argument("--force", action="store_true", help="re-download existing")
    args = ap.parse_args()

    sheets = json.loads((ROOT / "data" / "sheets.json").read_text())
    if args.sheet:
        sheets = [s for s in sheets if s["id"] == args.sheet]
    only = set(args.only.split(",")) if args.only else None

    # One download per botanical name, shared between sheets that both use it.
    by_species: dict[str, list[tuple[str, str]]] = {}
    for s in sheets:
        plants = json.loads((ROOT / "data" / s["id"] / "plants.json").read_text())
        for p in plants:
            if only and p["key"] not in only:
                continue
            by_species.setdefault(p["botanical"], []).append((s["id"], p["key"]))

    credits_path = ROOT / "images" / "plants" / "CREDITS.json"
    credits = json.loads(credits_path.read_text()) if credits_path.exists() else {}

    missing: list[str] = []
    fell_back: list[str] = []
    done = 0

    for botanical, uses in sorted(by_species.items()):
        slug = re.sub(r"[^a-z0-9]+", "-", botanical.lower()).strip("-")
        large = ROOT / "images" / "plants" / f"{slug}.jpg"
        if large.exists() and not args.force:
            print(f"  = {botanical} (have it)")
            done += 1
            continue

        print(f"  + {botanical}")
        species = strip_cultivar(botanical)
        genus = (species or botanical).split()[0]
        used_species_photo = False

        hit = pick(SEARCH_OVERRIDE.get(botanical, botanical), genus)
        if hit is None and species and species.lower() != botanical.lower():
            print(f"      no cultivar match; trying species '{species}'")
            hit = pick(species, genus)
            used_species_photo = hit is not None
        if hit is None and len(species.split()) > 1:
            print(f"      no species match; trying genus '{genus}'")
            hit = pick(genus, genus)
            used_species_photo = hit is not None
        if hit is None:
            print(f"      !! nothing usable found")
            missing.append(botanical)
            continue

        try:
            im = download(hit["url"])
        except Exception as e:                                # noqa: BLE001
            print(f"      !! download failed: {e}")
            missing.append(botanical)
            continue

        save(im, large, LARGE)
        save(im, ROOT / "images" / "plants" / f"{slug}-sm.jpg", SMALL)
        credits[slug] = {
            "botanical": botanical,
            "file": hit["title"],
            "author": hit["author"],
            "licence": hit["licence"],
            "source": hit["descriptionurl"],
            "showsSpeciesNotCultivar": used_species_photo,
            "usedBy": [f"{sid}:{key}" for sid, key in uses],
        }
        if used_species_photo:
            fell_back.append(botanical)
        print(f"      {hit['licence']} - {hit['author'][:60]}")
        done += 1

    credits_path.parent.mkdir(parents=True, exist_ok=True)
    credits_path.write_text(json.dumps(credits, indent=1, sort_keys=True) + "\n")

    print(f"\n{done} species with photos, {len(missing)} without")
    if fell_back:
        print(f"{len(fell_back)} show the parent species rather than the cultivar:")
        for b in fell_back:
            print(f"  - {b}")
    if missing:
        print("No usable photo found for:")
        for b in missing:
            print(f"  - {b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
