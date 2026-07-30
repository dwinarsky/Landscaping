# Pearson Residence — interactive landscape plan

An interactive map of the planting plan for **13165 Ten Oak Court, Saratoga, CA**, drawn by
Landworks Inc. in December 2001 and revised July 2002.

The plan only exists on paper. This turns a photograph of it into something usable in the garden:
pan and zoom the drawing, tap a bed to see everything planted there, or tap an individual hexagon
callout to see what goes at that exact spot and what it looks like grown.

No framework, no build step, no runtime dependencies — `index.html` plus vanilla ES modules and
JSON. Python under `tools/` is offline tooling used to produce the data, never at runtime.

## Run it locally

```sh
python3 -m http.server 8000
# then open http://localhost:8000
```

It must be served over HTTP; opening `index.html` from the filesystem fails because ES modules and
`fetch` are blocked on `file://`.

## What is mapped

| Sheet | Area | Species | Plants | Callouts | Areas |
|-------|------|---------|--------|----------|-------|
| 3 of 7 | Front yard | 41 | 281 | 91 | 11 |
| 4 of 7 | Back yard | 36 | 268 | 65 | 9 |

549 plants and 156 callouts in total.

Sheets 1, 2, 5, 6 and 7 (irrigation, lighting, grading and construction details) were not
photographed and are not included. The data model handles any number of sheets — adding one is a
data-only change.

### Plant keys are scoped per sheet

The two sheets reuse the same two-letter keys for **different plants**:

| Key | Front yard | Back yard |
|-----|------------|-----------|
| `AA` | *Agapanthus africanus*, 21 | *Agapanthus africanus* **'Blue'**, 45 |
| `HA` | *Hemerocallis* 'Aztec Gold' (day lily), 11 | ***Heteromeles arbutifolia*** (Toyon), 1 |
| `BT` | *Berberis thu.* **'Crimson Pygmy'**, 6 | *Berberis thu.* **'Atropurpurea'**, 1 |

Nineteen keys appear on both sheets and eighteen of them mean something different. There is
deliberately no global key lookup anywhere in the code — `data.js` builds one table per sheet, and
`tools/validate.py` asserts the collisions still exist so the two legends can never be merged by
accident.

## How the data was produced

Everything runs through `tools/`, in this order.

```sh
python3 -m pip install -r requirements.txt

# 1. Flatten the phone photo into a square-on plan image.
python3 tools/prepare_plan.py --sheet sheet-03-front --rotate 270

# 2. Find the hexagon callouts on the drawing.
python3 tools/detect_callouts.py --sheet sheet-03-front --region 0,150,2520,2665

# 3. Render them magnified so the keys and counts can be read.
python3 tools/contact_sheet.py --sheet sheet-03-front

# 4. Turn those readings into callouts.json.
python3 tools/build_callouts.py --sheet sheet-03-front

# 5. Crop a zoomed view of the plan for each garden area.
python3 tools/crop_zones.py --sheet sheet-03-front

# 6. Fetch photos: a whole-plant shot and a close-up per species.
python3 tools/fetch_plant_photos.py

# 6b. Only if a photo looks wrong - build contact sheets and pick by eye,
#     then pin the choice in the PICKS table in fetch_plant_photos.py.
python3 tools/review_photos.py --combined --species "Daphne odora" "Myrsine africana"

# 7. Check it all against the blueprint's own arithmetic.
python3 tools/validate.py
```

### The coordinate system

`prepare_plan.py` detects the sheet of paper against the carpet (by saturation — brightness alone
cannot separate aged paper from tan carpet), perspective-warps it flat, evens out the lighting, and
emits WebP rasters. The dimensions of that rectified image define **the one coordinate space used
everywhere**: zone polygons, callout positions, and the SVG `viewBox` are all in its pixels. Re-run
`prepare_plan.py` with different arguments and every coordinate in `data/` shifts, so don't.

### Reading the callouts

Contour analysis cannot isolate the hexagons — every one is fused to its leader line, so the
outline is never a closed contour. Detection instead template-matches a synthetic hexagon with the
interior masked out, then verifies each candidate structurally by looking for the three horizontal
rules a real callout has (flat top edge, full-width divider, flat bottom edge).

The keys and counts themselves are read by eye off `contact_sheet.py` output and recorded in
`tools/build_callouts.py`. No OCR engine is available here, and the stylized lettering defeats the
ones that are.

### The legend is a checksum

The plant legend states a quantity per key; the drawing states a count per callout. Those must
agree, per key and in total, which turns 41 legend rows into a checksum over 91 hand-read hexagons.
`tools/validate.py` enforces it. The front yard reconciles **exactly** at 281 plants; the back yard
reconciles at 266 of 268 with one recorded gap (below). That is how missed callouts get found: the
front yard's `RF/4`, alone at the far west edge, showed up as a four-plant shortfall on one key, and
six more on the back sheet were tracked down the same way.

The checksum also caught two things a careful reading missed. Three back-yard callouts read `RF`
but had to be `RC` — `RF` was over by exactly 13 and `RC` short by exactly 13, and the three
callouts summed to 13. And the `LC` legend quantity turned out to be **11, not 1**, which only
became clear when two `LC` callouts totalling 11 refused to reconcile; re-reading the legend row at
full resolution confirmed it.

## Things the data records honestly

- **`MA` vs `MY`.** The drawing labels every *Myrsine africana* callout `MA`, but the legend splits
  the species into `MA` (4 plants, 5 gallon) and `MY` (22, 1 gallon). The three `MA` callouts total
  26 — exactly 4 + 22. The `MA/10` and `MA/12` callouts are taken as the 22 one-gallon plants; that
  split is inferred, is marked `inferred: true` in `callouts.json`, and is shown as a caveat in the
  app.
- **Area outlines are approximate.** They are traced over a photograph of a paper drawing. The
  blueprint carries the same caveat itself: *"We are not professional surveyors and intend these
  plans only as an approximation of actual site conditions."*
- **Growing notes are mine, not the designer's.** Botanical name, common name, quantity, container
  size and remarks are transcribed verbatim. Plant type, mature size, sun, water, bloom season and
  the descriptive prose are added context, labelled as such in the app.
- **Some photos show the species, not the cultivar.** Wikimedia often has no photo of a specific
  cultivar. Those are flagged in `CREDITS.json` and captioned accordingly rather than implying a
  match. Nothing is substituted with a wrong plant.
- **Two species have no whole-plant photo at all** on Commons - the daylily and the hybrid tea
  rose. Their cards say "Closest available" instead of "Whole plant" and state that no habit shot
  exists, rather than captioning a flower macro as if it showed the plant.
- **Two back-yard plants could not be placed.** The legend calls for 8 Gaiety Girl Tea Tree but
  only three callouts are legible, totalling 6. The sheet has a crease and glare across part of the
  plan and the fourth callout is most likely lost there. Rather than invent a location, the gap is
  declared in `sheets.json`, surfaced on the plant card in the app, and downgraded by `validate.py`
  from an error to a warning — so the gate still fails on any *new* mismatch.
- **The plan is from 2001.** It records design intent, not what is alive in the garden today.

## Editing the map

Open with `?edit=1` to drag area outlines and callout markers, then copy the corrected JSON back
into `data/`. Useful because the outlines are a tracing and the marker positions come from shape
detection — both are close, neither is authoritative.

Other URL parameters, all shareable:

```
?sheet=sheet-03-front
?sheet=sheet-03-front&zone=lawn-and-magnolia
?sheet=sheet-03-front&plant=LM
```

## Adding your own photos

Drop a file at `images/plants/<species-slug>-mine.jpg` and the app prefers it over the Wikimedia
one — handy for photographing what is actually growing in the garden now.

## One file you can keep and pass on

`landscape-plan.html` is the whole map as a single self-contained file: both blueprints, every
photo and all the data inlined, no network needed to open it. It sits at the root of this
repository — download it from there, or from the About panel when running the site locally.

It is genuinely offline - opened from a phone's downloads folder with no signal it still pans,
zooms, searches and shows every photo. Email it, AirDrop it, put it on a USB stick; whoever opens
it needs nothing but a browser.

**Open it in a real browser, not an app's file preview.** The map is drawn in JavaScript, and the
preview panes built into mail and chat apps commonly strip scripts. Everything else still renders,
so the result used to be a blank page with no explanation. The page now detects this and says what
to do, but the fix is the same: save the file, then open it in Safari, Chrome or Firefox.

Rebuild it after any change to the data or photos:

```sh
python3 tools/build_artifact.py --out landscape-plan.html \
  --plan-width 1500 --zone-width 500 --photo-width 270 --detail-width 190
```

Those widths hold it near 3.5 MB. Raise them for a sharper copy and a bigger file.

## This is not published anywhere

It was on GitHub Pages briefly and is not any more. Pages serves **publicly whatever the
repository's visibility** — private Pages is a GitHub Enterprise feature — and this map is centred
on a private home with the address in its title.

So there is no public URL. Use it one of two ways:

- `landscape-plan.html` — the single self-contained file above. Hand it to whoever should have it.
- Run it locally with `python3 -m http.server 8000` for the full version, editor mode included.

`.github/workflows/pages.yml` therefore has **no deploy job**, only the data checksum gate. That is
deliberate: a deploy step left in it would put the address back on the open internet on the next
push, silently.

`.nojekyll` is a leftover from that period. Harmless, and correct again if Pages is ever re-enabled.

## Plant photos

Each species gets two: a **habit** shot showing the whole plant, and a **close-up** of the flower
or foliage. The habit shot leads, because standing in the garden the useful question is whether
this is a groundcover or a fifteen-foot shrub, and a flower macro cannot answer that.

Getting habit shots out of Commons is harder than it sounds. It is overwhelmingly flower macros,
and picking "the largest, most landscape-shaped result" returns those plus scenery from wherever
the plant happens to grow. The first pass produced a car park for *Hardenbergia*, a street with
power lines for *Podocarpus*, a building facade for *Pyrus*, bare dirt for dwarf agapanthus, a moth
for star jasmine, and plant labels on stakes for *Daphne* and star jasmine again.

`fetch_plant_photos.py` now pools candidates from several queries and scores each on what its title
and description say the picture shows, rejecting signs, herbarium sheets, insects and streetscapes.
That fixes most of them. The rest cannot be fixed by keywords - a file captioned only "Daphne
odora" really can be a label on a stake, and an insect can be named in Latin
(*Autographa gamma* on a jasmine flower). Those 34 species are pinned by filename in the `PICKS`
table, chosen by eye from `review_photos.py` contact sheets. 55 of 57 species now have a genuine
whole-plant photo.

## Photo credits

Plant photographs come from Wikimedia Commons under CC0, CC BY and CC BY-SA licences. Author,
licence and source URL for every photo are in `images/plants/CREDITS.json` and are shown beneath
each photo and on the About page in the app.

The blueprint itself is © Landworks Inc., 2001.
