#!/usr/bin/env python3
"""Fetch openly-licensed plant photos from Wikimedia Commons.

Two photos per species, because they answer different questions:

  habit   - the whole plant, so you can tell a groundcover from a 15 ft shrub.
            This is the one shown large on the plant card.
  detail  - the flower or foliage close-up, shown smaller underneath.

Commons is overwhelmingly flower macros, and a naive "biggest, most landscape-
shaped result" picker returns those plus scenery from wherever the plant grows -
car parks, streets, buildings, plant labels, an insect on a petal. So candidates
are pooled from several queries and scored on what the file title and
description say the picture actually shows.

Only clearly redistributable licences are kept, and author/licence/source go
into CREDITS.json so every photo can be attributed - CC-BY and CC-BY-SA
require it.

Usage:
    python3 tools/fetch_plant_photos.py
    python3 tools/fetch_plant_photos.py --only AA,BA --force
    python3 tools/fetch_plant_photos.py --sheet sheet-03-front --report
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
API = "https://commons.wikimedia.org/w/api.php"
UA = "PearsonResidenceLandscapeMap/1.0 (personal garden reference; contact via repo)"

OK_LICENCES = ("cc0", "cc-by", "cc-by-sa", "public domain", "pd-", "attribution")
BAD_LICENCES = ("nc", "nd", "fair use", "non-free")

LARGE, SMALL, DETAIL = 1024, 320, 640

# ---------------------------------------------------------------- vocabulary

# Words suggesting the picture shows the plant as a whole.
HABIT_WORDS = (
    "habit", "habitus", "shrub", "bush", "tree", "hedge", "plant", "plants",
    "growing", "grown", "form", "whole", "specimen", "bed", "border",
    "planting", "foliage", "canopy", "trunk", "groundcover", "ground cover",
    "arbuste", "strauch", "pianta", "planta", "in garden", "garden",
)

# Words suggesting a close-up of one part.
DETAIL_WORDS = (
    "flower", "flowers", "floral", "bloom", "blossom", "inflorescence",
    "close-up", "closeup", "close up", "macro", "detail", "bud", "buds",
    "petal", "petals", "stamen", "pistil", "corolla", "calyx",
    "fruit", "fruits", "berry", "berries", "seed", "seeds", "cone",
    "leaf", "leaves", "blüte", "fleur", "flor",
)

# Pictures that are not usable as a plant portrait at all.
REJECT_WORDS = (
    "sign", "signage", "label", "plaque", "nameplate", "tag", "placard",
    "herbarium", "specimen sheet", "illustration", "drawing", "engraving",
    "botanical print", "plate", "map", "distribution", "diagram", "chart",
    "logo", "coat of arms",
    "moth", "butterfly", "bee", "wasp", "hoverfly", "fly", "insect", "beetle",
    "spider", "caterpillar", "aphid", "snail", "bird", "lizard",
    "street", "road", "highway", "car park", "parking", "building", "house",
    "church", "station", "bridge", "monument", "cemetery", "graveyard",
    "interior", "shop", "market", "nursery pot", "seedling in pot",
)


def has(text: str, words) -> int:
    return sum(1 for w in words if w in text)


# ------------------------------------------------------------ HTTP plumbing

MIN_INTERVAL = 1.4
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def fetch(url: str, timeout: int = 60) -> bytes:
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
    return json.loads(fetch(f"{API}?{urllib.parse.urlencode(params)}", timeout=45).decode())


# ------------------------------------------------------------ name handling

# The blueprint abbreviates species epithets and carries a few spelling slips.
ABBREV = {
    "thu.": "thunbergii", "vio.": "violacea", "sco.": "scoparium",
    "par.": "parvifolium", "o.": "officinalis",
    "hyb.": "", "var.": "", "noatratum": "", "x": "", "X": "",
}
CORRECTIONS = {"phorium": "Phormium"}

SEARCH_OVERRIDE = {
    "Rosa var. noatratum 'Flower Carpet'": "Rosa Flower Carpet",
    "Rosa 'Hybrid Tea'": "Rosa hybrid tea rose",
    "Lagerstroemia X 'Natchez'": "Lagerstroemia indica",
    "Phorium 'Gold Sword'": "Phormium tenax",
}


# Hand-picked files, chosen by eye from tools/review_photos.py contact sheets.
# Scoring cannot distinguish a plant portrait from a plant label on a stake, an
# insect named in Latin, or a nursery yard, so these are pinned by slug.
# habit = the whole plant; detail = the close-up. None means none exists.
PICKS: dict[str, dict[str, str | None]] = {
    "agapanthus-africanus": {
        "habit": "File:Agapanthus africanus 17zz.jpg",
        "detail": "File:Agapanthus africanus 01.JPG"},
    "agapanthus-africanus-blue": {
        "habit": "File:Agapanthus africanus 17zz.jpg",
        "detail": "File:Agapanthus africanus 01.JPG"},
    "agapanthus-africanus-peter-pan": {
        "habit": "File:Agapanthus africanus 17zz.jpg",
        "detail": "File:Agapanthus africanus 01.JPG"},
    "daphne-odora-marginata": {
        "habit": "File:Daphne Odora Capel Manor Enfield London England 01.jpg",
        "detail": "File:Daphne odora, 'Perfume Princess' - geograph.org.uk - 7967067.jpg"},
    "trachelospermum-jasminoides": {
        "habit": "File:Trachelospermum jasminoides - 01.jpg",
        "detail": "File:Confederate Jasmine -- Trachelospermum jasminoides.jpg"},
    "podocarpus-macrophyllus-maki": {
        "habit": "File:Podocarpus macrophyllus.jpg",
        "detail": "File:Podocarpus macrophyllus (seed s5).jpg"},
    "lavatera-thuringiaca-barnsley": {
        "habit": "File:Lavatera thuringiaca Uppsala.jpg",
        "detail": "File:Lavatera thuringiaca kz01.jpg"},
    "leptospermum-sco-gaiety-girl": {
        "habit": "File:Leptospermum scoparium 'Gaiety Girl' kz01.jpg",
        "detail": "File:Leptospermum scoparium 'Gaiety Girl' kz02.jpg"},
    "leptospermum-sco-nanum-tui": {
        "habit": "File:Leptospermum scoparium 'Jubilee' kz1.jpg",
        "detail": "File:Leptospermum scoparium 'Wiri Donna' kz2.jpg"},
    "rosa-var-noatratum-flower-carpet": {
        "habit": "File:CBG Evening Island - Rosa Flower Carpet Pink, Nepeta 'Walker's Low', Allium giganteum 150623 (20325938812).jpg",
        "detail": "File:Rosa 'Flower Carpet Scarlet' 2a.jpg"},
    "pennisetum-eaton-canyon": {
        "habit": "File:Pennisetum setaceum kz01.jpg",
        "detail": "File:Pennisetum alopecuroides (Lampenpoetsersgras) 02.JPG"},
    "phorium-gold-sword": {
        "habit": "File:Phormium tenax 126439719.jpg",
        "detail": "File:Phormium tenax 'Variegata' kz01.jpg"},
    "osmanthus-fragrans": {
        "habit": "File:Osmanthus fragrans(Thunb.)Lour..JPG",
        "detail": "File:Osmanthus fragrans 20151023.JPG"},
    "cerastium-tomentosum": {
        "habit": "File:Cerastium tomentosum 02.jpg",
        "detail": "File:Cerastium tomentosum 2023-05-28 6525.jpg"},
    "pittosporum-tobira-wheeleri": {
        "habit": "File:Hedge Pittosporum tobira July 2026-1.jpg",
        "detail": "File:Pittosporum Tobira (211554843).jpeg"},
    "pittosporum-tobira-wheelerii": {
        "habit": "File:Hedge Pittosporum tobira July 2026-1.jpg",
        "detail": "File:Pittosporum Tobira (211554843).jpeg"},
    "pittosporum-tobira-variegata": {
        "habit": "File:Hedge Pittosporum tobira July 2026-1.jpg",
        "detail": "File:Pittosporum tobira 'Variegata' kz03.jpg"},
    "xylosma-congestum": {
        "habit": "File:Xylosma congesta 371548739.jpg",
        "detail": "File:Xylosma-congestum.jpg"},
    "myrsine-africana": {
        "habit": "File:Myrsine africana - Cape Town.JPG",
        "detail": "File:Myrsine africana 0327.jpg"},
    "hardenbergia-vio-happy-wanderer": {
        "habit": "File:Hardenbergia violacea 1c.JPG",
        "detail": "File:Hardenbergia violacea 2c.JPG"},
    "hardenbergia-vio-mini-ha-ha": {
        "habit": "File:Hardenbergia violacea 1c.JPG",
        "detail": "File:Hardenbergia violacea 2c.JPG"},
    "michelia-figo-port-wine": {
        "habit": "File:Magnolia figo (Michelia fuscata) - Zilker Botanical Garden - Austin, Texas - DSC08912.jpg",
        "detail": "File:Michelia figo--IMG 20180326 175343.jpg"},
    "rosa-hybrid-tea": {
        "habit": None,
        "detail": "File:Hybrid Tea Rose (Rosa ) 'Peace'.jpg"},
    "alyogyne-huegelii": {
        "habit": "File:Alyogyne huegelii.jpg",
        "detail": "File:Alyogyne.JPG"},
    "ceratostigma-plumbaginoides": {
        "habit": "File:Ceratostigma plumbaginoides 02.jpg",
        "detail": "File:Ceratostigma plumbaginoides - Fleurs.jpg"},
    "clytostoma-callistegioides": {
        "habit": "File:Clytostoma callistegioides - Auckland Domain Winter Garden - Auckland, NZ - DSC06995.jpg",
        "detail": "File:Clytostoma callistegioides syn Bignonia callistegioides.jpg"},
    "dicksonia-antarctica": {
        "habit": "File:2025. Dicksonia antarctica. Osmunda regalis. Miscanthus sinensis Andersson. Alameda de Santiago. Galiza-2.jpg",
        "detail": "File:Dicksonia antarctica (sorus).jpg"},
    "dietes-bicolor": {
        "habit": "File:Dietes bicolor, Jacksonville Zoo.jpg",
        "detail": "File:Dietes bicolor (5360604831).jpg"},
    "lantana-montevidensis": {
        "habit": "File:Lantana-montevidensis-plants.jpg",
        "detail": "File:Flower of Lantana montevidensis (Trailing lantana) 2026-02-28 01.jpg"},
    "magnolia-rustica-rubra": {
        "habit": "File:Magnolia soulangeana - Lancut - Kroton 001.JPG",
        "detail": "File:Magnolia soulangeana.jpg"},
    "osmanthus-delavayi": {
        "habit": "File:Osmanthus delavayi2.jpg",
        "detail": "File:Osmanthus delavayi0.jpg"},
    "bougainvillea-spectabilis": {
        "habit": "File:Bougainvillea (40763).jpg",
        "detail": "File:Bougainvillea 19.jpg"},
    "coleonema-pulchrum": {
        "habit": 'File:Alecrín ( Coleonema pulchrum) - panoramio.jpg',
        "detail": 'File:Coleonema pulchrum - IES Perdouro (Escaleiras dereita).jpg'},
    "coleonema-pulchrum-sunset-gold": {
        "habit": 'File:Alecrín ( Coleonema pulchrum) - panoramio.jpg',
        "detail": 'File:Coleonema pulchrum - IES Perdouro (Escaleiras dereita).jpg'},
}


def by_title(titles: list[str]) -> dict[str, dict]:
    """Look up specific Commons files and package them like gather() results."""
    out = {}
    for page in image_info([t for t in titles if t]).values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        meta = info.get("extmetadata", {})
        ok, lic = licence_ok(meta)
        if not ok:
            print(f"      !! {page.get('title')} licence not usable: {lic}")
            continue
        out[page["title"]] = {
            "title": page["title"],
            "text": page["title"].lower(),
            "url": info.get("thumburl") or info["url"],
            "descriptionurl": info.get("descriptionurl", ""),
            "licence": lic,
            "author": clean_html(meta.get("Artist", {}).get("value", "")) or "Unknown",
            "ratio": 1.0,
            "width": info.get("width", 0),
        }
    return out


def strip_cultivar(botanical: str) -> str:
    s = re.sub(r"'[^']*'", " ", botanical)
    s = re.sub(r'"[^"]*"', " ", s)
    words = []
    for w in s.split():
        w = ABBREV.get(w, w)
        w = CORRECTIONS.get(w.lower(), w)
        if w:
            words.append(w)
    return " ".join(words)


# --------------------------------------------------------------- candidates

def search_titles(term: str, limit: int) -> list[str]:
    try:
        r = api({"action": "query", "list": "search",
                 "srsearch": f"{term} filetype:bitmap", "srnamespace": "6",
                 "srlimit": str(limit)})
    except Exception as e:                                    # noqa: BLE001
        print(f"      search failed: {e}")
        return []
    return [h["title"] for h in r.get("query", {}).get("search", [])]


def image_info(titles: list[str]) -> dict:
    if not titles:
        return {}
    try:
        r = api({"action": "query", "titles": "|".join(titles[:50]),
                 "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime",
                 "iiurlwidth": str(LARGE)})
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
    return " ".join(re.sub(r"<[^>]+>", "", s or "").split())[:400]


def gather(species: str, genus: str) -> list[dict]:
    """Pool candidates from a plain search and a habit-biased one."""
    titles: list[str] = []
    for term, limit in ((species, 30), (f"{species} habit plant shrub tree", 20)):
        for t in search_titles(term, limit):
            if t not in titles:
                titles.append(t)

    out = []
    for page in image_info(titles).values():
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        if not info.get("mime", "").startswith("image/"):
            continue
        title = page.get("title", "")
        if genus not in title.lower():
            continue                       # relevance guard: keep the genus
        w, h = info.get("width", 0), info.get("height", 0)
        if w < 500 or h < 380:
            continue
        meta = info.get("extmetadata", {})
        ok, lic = licence_ok(meta)
        if not ok:
            continue

        desc = clean_html(meta.get("ImageDescription", {}).get("value", ""))
        text = f"{title} {desc}".lower()
        if has(text, REJECT_WORDS):
            continue

        out.append({
            "title": title,
            "text": text,
            "url": info.get("thumburl") or info["url"],
            "descriptionurl": info.get("descriptionurl", ""),
            "licence": lic,
            "author": clean_html(meta.get("Artist", {}).get("value", "")) or "Unknown",
            "ratio": (w / h) if h else 1.0,
            "width": w,
        })
    return out


def score_habit(c: dict) -> float:
    """Higher when the picture looks like the whole plant."""
    s = 3.0 * has(c["text"], HABIT_WORDS) - 2.5 * has(c["text"], DETAIL_WORDS)
    if 1.1 <= c["ratio"] <= 1.9:
        s += 0.6                            # landscape framing suits a portrait
    return s


def score_detail(c: dict) -> float:
    """Higher when the picture is a close-up of flower or foliage."""
    return 3.0 * has(c["text"], DETAIL_WORDS) - 1.0 * has(c["text"], HABIT_WORDS)


def choose(pool: list[dict]) -> tuple[dict | None, dict | None]:
    if not pool:
        return None, None
    habit = max(pool, key=score_habit)
    if score_habit(habit) <= 0:
        habit = None
    rest = [c for c in pool if habit is None or c["title"] != habit["title"]]
    detail = max(rest, key=score_detail) if rest else None
    if detail is not None and score_detail(detail) <= 0:
        detail = None
    # Nothing scored as a habit shot: fall back to the best available so the
    # card is not empty, and let the caller flag it.
    if habit is None:
        habit = max(pool, key=lambda c: (score_detail(c), c["width"]))
        if detail is not None and detail["title"] == habit["title"]:
            detail = None
    return habit, detail


# ------------------------------------------------------------------- saving

def download(url: str) -> Image.Image:
    return Image.open(io.BytesIO(fetch(url, timeout=90))).convert("RGB")


def save(im: Image.Image, path: pathlib.Path, width: int) -> None:
    w, h = im.size
    if w > width:
        im = im.resize((width, max(1, round(h * width / w))), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=82, optimize=True, progressive=True)


def credit_entry(hit: dict, species_photo: bool) -> dict:
    return {
        "file": hit["title"],
        "author": hit["author"],
        "licence": hit["licence"],
        "source": hit["descriptionurl"],
        "showsSpeciesNotCultivar": species_photo,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet")
    ap.add_argument("--only", help="comma-separated plant keys")
    ap.add_argument("--slug", help="comma-separated species slugs")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--report", action="store_true",
                    help="print what each photo was chosen as, then exit")
    args = ap.parse_args()

    sheets = json.loads((ROOT / "data" / "sheets.json").read_text())
    if args.sheet:
        sheets = [s for s in sheets if s["id"] == args.sheet]
    only = set(args.only.split(",")) if args.only else None

    by_species: dict[str, list[str]] = {}
    for s in sheets:
        for p in json.loads((ROOT / "data" / s["id"] / "plants.json").read_text()):
            if only and p["key"] not in only:
                continue
            by_species.setdefault(p["botanical"], []).append(f"{s['id']}:{p['key']}")

    out_dir = ROOT / "images" / "plants"
    credits_path = out_dir / "CREDITS.json"
    credits = json.loads(credits_path.read_text()) if credits_path.exists() else {}

    if args.report:
        for slug, c in sorted(credits.items()):
            kinds = [k for k in ("habit", "detail") if c.get(k)]
            print(f"  {slug:44s} {','.join(kinds) or 'NONE':13s} "
                  f"{c.get('habit', {}).get('file', '')[:60]}")
        return 0

    no_habit: list[str] = []
    no_detail: list[str] = []
    missing: list[str] = []

    for botanical, uses in sorted(by_species.items()):
        slug = re.sub(r"[^a-z0-9]+", "-", botanical.lower()).strip("-")
        if args.slug and slug not in args.slug.split(","):
            continue
        habit_path = out_dir / f"{slug}.jpg"
        if habit_path.exists() and not args.force and credits.get(slug, {}).get("habit"):
            print(f"  = {botanical}")
            continue

        print(f"  + {botanical}")
        species = strip_cultivar(botanical)
        genus = (species or botanical).split()[0].lower()
        term = SEARCH_OVERRIDE.get(botanical, species or botanical)

        used_species_photo = term.lower() != botanical.lower()
        pick = PICKS.get(slug)

        if pick:
            found = by_title([pick.get("habit"), pick.get("detail")])
            habit = found.get(pick.get("habit"))
            detail = found.get(pick.get("detail"))
            if pick.get("habit") and habit is None:
                print(f"      !! pinned habit file unavailable: {pick['habit']}")
            hand_picked = True
        else:
            pool = gather(term, genus)
            if not pool and " " in (species or ""):
                print(f"      nothing for '{term}'; trying genus '{genus}'")
                pool = gather(genus, genus)
                used_species_photo = True
            if not pool:
                print("      !! nothing usable found")
                missing.append(botanical)
                continue
            habit, detail = choose(pool)
            hand_picked = False

        if habit is None and detail is None:
            print("      !! nothing usable found")
            missing.append(botanical)
            continue
        entry = {"botanical": botanical, "usedBy": uses}

        if habit:
            try:
                im = download(habit["url"])
                save(im, habit_path, LARGE)
                save(im, out_dir / f"{slug}-sm.jpg", SMALL)
                # isHabit says whether this really shows the whole plant. When
                # it does not, the app drops the "Whole plant" label rather
                # than claiming something the picture does not show.
                real = hand_picked or score_habit(habit) > 0
                entry["habit"] = {**credit_entry(habit, used_species_photo),
                                  "isHabit": real, "handPicked": hand_picked}
                print(f"      habit : {habit['title'][:58]}"
                      f"{'' if real else '  (best available, not a habit shot)'}")
                if not real:
                    no_habit.append(botanical)
            except Exception as e:                            # noqa: BLE001
                print(f"      !! habit download failed: {e}")
        else:
            no_habit.append(botanical)

        if detail:
            try:
                im = download(detail["url"])
                save(im, out_dir / f"{slug}-detail.jpg", DETAIL)
                entry["detail"] = {**credit_entry(detail, used_species_photo),
                                   "handPicked": hand_picked}
                print(f"      detail: {detail['title'][:58]}")
            except Exception as e:                            # noqa: BLE001
                print(f"      !! detail download failed: {e}")
        else:
            no_detail.append(botanical)

        if "habit" in entry or "detail" in entry:
            credits[slug] = entry
        credits_path.parent.mkdir(parents=True, exist_ok=True)
        credits_path.write_text(json.dumps(credits, indent=1, sort_keys=True) + "\n")

    print(f"\n{len(credits)} species in CREDITS.json")
    if no_habit:
        print(f"{len(no_habit)} without a true whole-plant shot (using best available):")
        for b in no_habit:
            print(f"  - {b}")
    if no_detail:
        print(f"{len(no_detail)} without a separate close-up")
    if missing:
        print("No usable photo at all for:")
        for b in missing:
            print(f"  - {b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
