/* Data loading and the per-sheet plant lookup.
 *
 * The single most important rule in this project lives here: plant keys are
 * scoped to a sheet. Sheet 3 and sheet 4 reuse the same two-letter keys for
 * different plants - 'HA' is a gold daylily in the front yard and Toyon in the
 * back - so there is deliberately no global key lookup to reach for.
 *
 * When bundled into a single self-contained file, the build inlines the JSON as
 * window.__PLAN_DATA__ and the images as window.__PLAN_ASSETS__; otherwise
 * everything is fetched from disk. Nothing else in the app needs to know which.
 */

const INLINE = typeof window !== "undefined" ? window.__PLAN_DATA__ : null;
const ASSETS = (typeof window !== "undefined" && window.__PLAN_ASSETS__) || null;

/** Resolve a repo-relative asset path, honouring an inlined asset map.
 *
 * The single-file bundle ships one photo per species rather than both the full
 * and thumbnail sizes, so a miss on the full size falls back to the thumbnail
 * instead of embedding the same image twice.
 */
export function asset(path) {
  if (!ASSETS) return path;
  if (Object.prototype.hasOwnProperty.call(ASSETS, path)) return ASSETS[path];
  const thumb = path.replace(/\.jpg$/, "-sm.jpg");
  if (thumb !== path && Object.prototype.hasOwnProperty.call(ASSETS, thumb)) {
    return ASSETS[thumb];
  }
  return path;
}

/** True when an asset actually exists in this build. */
export function hasAsset(path) {
  if (!ASSETS) return true;           // served from disk: assume present
  return Object.prototype.hasOwnProperty.call(ASSETS, path);
}

async function json(path) {
  if (INLINE && INLINE[path]) return INLINE[path];
  const r = await fetch(path);
  if (!r.ok) throw new Error(`could not load ${path} (${r.status})`);
  return r.json();
}

function slug(botanical) {
  return botanical.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

export async function loadPlan() {
  const [sheetList, meta, siteLegend, credits] = await Promise.all([
    json("data/sheets.json"),
    json("data/meta.json"),
    json("data/site-legend.json"),
    json("images/plants/CREDITS.json").catch(() => ({})),
  ]);

  const sheets = [];
  for (const s of sheetList) {
    // `mapped` says whether this sheet's callouts have been read off the
    // drawing yet. Sheets awaiting that work still show their plan and legend.
    const [plants, callouts, zones] = await Promise.all([
      json(`data/${s.id}/plants.json`),
      s.mapped ? json(`data/${s.id}/callouts.json`) : [],
      s.mapped ? json(`data/${s.id}/zones.json`) : [],
    ]);

    // Per-sheet key table. Never merge these across sheets.
    const plantByKey = new Map(plants.map((p) => [p.key, p]));

    const gaps = new Map((s.discrepancies || []).map((d) => [d.key, d]));

    for (const p of plants) {
      p.sheet = s.id;
      p.gap = gaps.get(p.key) || null;
      p.slug = slug(p.botanical);
      // Two photos answer different questions: the habit shot shows how big
      // and what shape the plant is, the detail shot shows the flower.
      p.photo = `images/plants/${p.slug}.jpg`;
      p.photoSmall = `images/plants/${p.slug}-sm.jpg`;
      p.photoDetail = `images/plants/${p.slug}-detail.jpg`;
      const cred = credits[p.slug] || null;
      p.credit = cred?.habit || null;
      p.creditDetail = cred?.detail || null;
      // A few species have no whole-plant photo on Commons at all. Show the
      // close-up as the main image rather than no image, labelled honestly.
      if (!p.credit && p.creditDetail) {
        p.photo = p.photoDetail;
        p.credit = { ...p.creditDetail, isHabit: false };
        p.creditDetail = null;
      }
    }

    for (const c of callouts) {
      c.sheet = s.id;
      // resolvedKey exists where the drawing and the legend disagree.
      c.lookupKey = c.resolvedKey || c.key;
      c.plant = plantByKey.get(c.lookupKey) || null;
    }

    const zoneById = new Map(zones.map((z) => [z.id, z]));
    for (const z of zones) {
      z.sheet = s.id;
      z.crop = `images/${s.id}/zones/${z.id}.webp`;
      z.callouts = [];
      z.centroid = centroid(z.polygon);
    }

    // Assign each callout to the zone containing it, then roll plants up.
    for (const c of callouts) {
      const hit = zones.find((z) => pointInPolygon(c.x, c.y, z.polygon));
      c.zoneId = hit ? hit.id : null;
      if (hit) hit.callouts.push(c);
    }
    for (const z of zones) z.plants = rollUp(z.callouts);

    sheets.push({
      ...s,
      plants,
      plantByKey,
      callouts,
      zones,
      zoneById,
      calloutsByKey: groupBy(callouts, (c) => c.lookupKey),
    });
  }

  return { sheets, meta, siteLegend, credits };
}

function groupBy(list, keyOf) {
  const m = new Map();
  for (const item of list) {
    const k = keyOf(item);
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(item);
  }
  return m;
}

/** Group a zone's callouts into one row per species, with a count. */
function rollUp(callouts) {
  const rows = new Map();
  for (const c of callouts) {
    if (!c.plant) continue;
    const row = rows.get(c.lookupKey) || {
      key: c.lookupKey, plant: c.plant, count: 0, spots: 0,
    };
    row.count += c.count;
    row.spots += 1;
    rows.set(c.lookupKey, row);
  }
  const order = { tree: 0, shrub: 1, vine: 2, perennial: 3, grass: 4, fern: 5, groundcover: 6 };
  return [...rows.values()].sort((a, b) => {
    const d = (order[a.plant.type] ?? 9) - (order[b.plant.type] ?? 9);
    return d || b.count - a.count;
  });
}

export function pointInPolygon(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < xi + ((y - yi) / (yj - yi)) * (xj - xi)) inside = !inside;
  }
  return inside;
}

function centroid(poly) {
  let x = 0, y = 0;
  for (const [px, py] of poly) { x += px; y += py; }
  return [x / poly.length, y / poly.length];
}

export function bboxOf(poly) {
  const xs = poly.map((p) => p[0]);
  const ys = poly.map((p) => p[1]);
  return {
    x: Math.min(...xs), y: Math.min(...ys),
    width: Math.max(...xs) - Math.min(...xs),
    height: Math.max(...ys) - Math.min(...ys),
  };
}
