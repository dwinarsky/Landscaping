/* The detail panel: what you get when you tap something.
 *
 * Three views - a garden area, one plant, or a single callout - plus the area
 * index and an about page. Everything transcribed from the blueprint is shown
 * as such; the horticultural notes I added are labelled separately so the
 * designer's spec is never confused with my commentary.
 */

import { asset, bboxOf, IS_BUNDLE } from "./data.js";
import { esc } from "./util.js";

/** The whole map as one file you can keep, send on, or use with no signal. */
const OFFLINE_FILE = "landscape-plan.html";

const TYPE_LABEL = {
  tree: "Trees", shrub: "Shrubs", vine: "Vines", perennial: "Perennials",
  grass: "Grasses", fern: "Ferns", groundcover: "Groundcover",
};

const backBtn = (label) => `
  <button type="button" class="p-back" data-act="back">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 6l-6 6 6 6"/></svg>
    ${esc(label)}
  </button>`;

function swatch(plant) {
  const c = plant.bloomColor || plant.foliageColor;
  if (!c) return "";
  return `<span class="swatch" style="background:${esc(c)}" title="${
    plant.bloomColor ? "Bloom colour" : "Foliage colour"}"></span>`;
}

function attribution(credit) {
  return `${esc(credit.author)} &middot; ${esc(credit.licence)} &middot;
    <a href="${esc(credit.source)}" target="_blank" rel="noopener noreferrer">Wikimedia Commons</a>`;
}

/** The whole plant, plus a close-up when one was found. */
function photoFigure(plant) {
  const credit = plant.credit;
  if (!credit) return "";

  const cultivar = plant.botanical.match(/'([^']*)'/)?.[1];
  const cultivarNote = credit.showsSpeciesNotCultivar
    ? `<br>Shows the species${cultivar ? `, not the '${esc(cultivar)}' cultivar` : ""}.`
    : "";

  const detail = plant.creditDetail ? `
    <figure class="p-fig p-fig-detail">
      <img src="${esc(asset(plant.photoDetail))}"
           alt="Close-up of ${esc(plant.common || plant.botanical)}"
           loading="lazy" decoding="async">
      <figcaption><span class="p-figtag">Close up</span>
        ${attribution(plant.creditDetail)}</figcaption>
    </figure>` : "";

  // Only claim "whole plant" when the picture actually shows one. Where
  // Commons has nothing but close-ups, say so rather than mislabel it.
  const isHabit = credit.isHabit !== false;
  const tag = isHabit ? "Whole plant" : "Closest available";
  const noHabitNote = isHabit ? ""
    : "<br>No whole-plant photo of this one on Wikimedia Commons.";

  return `
    <div class="p-photos">
      <figure class="p-fig p-fig-habit">
        <img src="${esc(asset(plant.photo))}"
             alt="${esc(plant.common || plant.botanical)}${isHabit ? " growing" : ""}"
             loading="lazy" decoding="async">
        <figcaption><span class="p-figtag${isHabit ? "" : " muted"}">${tag}</span>
          ${attribution(credit)}${cultivarNote}${noHabitNote}</figcaption>
      </figure>
      ${detail}
    </div>`;
}

function plantRow(row, { showSpots = true } = {}) {
  const p = row.plant;
  const thumb = p.credit
    ? `<img class="pthumb" src="${esc(asset(p.photoSmall))}" alt="" loading="lazy" decoding="async">`
    : `<span class="pkey">${esc(row.key)}</span>`;
  return `
    <li>
      <button type="button" class="prow" data-act="plant" data-key="${esc(row.key)}">
        ${thumb}
        ${swatch(p)}
        <span class="pmain">
          <span class="pcommon">${esc(p.common || p.botanical)}</span>
          <span class="pbot">${esc(p.botanical)}</span>
        </span>
        <span class="pqty">${row.count}<small>${
          showSpots && row.spots > 1 ? `${row.spots} spots` : esc(p.size)
        }</small></span>
      </button>
    </li>`;
}

function groupedPlantList(rows) {
  const groups = new Map();
  for (const r of rows) {
    const g = TYPE_LABEL[r.plant.type] || "Other";
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(r);
  }
  return [...groups]
    .map(([label, list]) => `
      <h3 class="p-sub">${esc(label)}</h3>
      <ul class="plist">${list.map((r) => plantRow(r)).join("")}</ul>`)
    .join("");
}

export class Panel {
  constructor({ panel, body, grab, scrim, app }) {
    this.panel = panel;
    this.body = body;
    this.scrim = scrim;
    this.app = app;
    this.stack = [];

    scrim.addEventListener("click", () => this.close());
    grab.addEventListener("click", () => this.close());

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this.isOpen()) this.close();
    });

    body.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-act]");
      if (!btn) return;
      const { act } = btn.dataset;
      if (act === "back") this.back();
      else if (act === "plant") this.app.showPlant(btn.dataset.key);
      else if (act === "zone") this.app.showZone(btn.dataset.zone, { frame: true });
      else if (act === "locate") this.app.locateSpecies(btn.dataset.key);
      else if (act === "frame") this.app.frameZone(btn.dataset.zone);
      else if (act === "areas") this.app.showAreas();
      else if (act === "about") this.app.showAbout();
    });

    this._dragToDismiss(grab);
  }

  isOpen() { return this.panel.classList.contains("is-open"); }

  open(html, { push = true } = {}) {
    if (push) this.stack.push(html);
    this.body.innerHTML = html;
    this.body.scrollTop = 0;
    this.panel.classList.add("is-open");
    document.body.classList.add("panel-open");
    if (window.matchMedia("(max-width: 899px)").matches) this.scrim.hidden = false;
  }

  replace(html) {
    this.stack = [html];
    this.open(html, { push: false });
  }

  back() {
    this.stack.pop();
    const prev = this.stack[this.stack.length - 1];
    if (prev) this.open(prev, { push: false });
    else this.close();
  }

  close() {
    this.panel.classList.remove("is-open");
    document.body.classList.remove("panel-open");
    this.scrim.hidden = true;
    this.stack = [];
    this.app.clearSelection();
  }

  /* --------------------------------------------------------------- views */

  zone(zone, sheet) {
    const total = zone.plants.reduce((n, r) => n + r.count, 0);
    const existing = (zone.existing || []).length
      ? `<h3 class="p-sub">Already there</h3>
         <ul class="chips">${zone.existing.map((f) => `<li class="chip">${esc(f)}</li>`).join("")}</ul>`
      : "";

    this.open(`
      <p class="p-eyebrow">${esc(sheet.label)} &middot; Area</p>
      <h2 class="p-title">${esc(zone.name)}</h2>
      <p class="p-blurb">${esc(zone.blurb)}</p>
      <img class="p-crop" src="${esc(asset(zone.crop))}"
           alt="The plan drawing for ${esc(zone.name)}" loading="lazy" decoding="async">
      <p class="p-desc">${esc(zone.description)}</p>
      <div class="p-tot"><b>${total}</b> plants &middot; ${zone.plants.length} species
        &middot; ${zone.callouts.length} callouts</div>
      ${existing}
      ${zone.plants.length ? groupedPlantList(zone.plants)
        : '<p class="p-note">No new planting is called out in this area.</p>'}
      <div class="p-actions">
        <button type="button" class="btn" data-act="frame" data-zone="${esc(zone.id)}">Zoom here on the plan</button>
        <button type="button" class="btn" data-act="areas">All areas</button>
      </div>`);
  }

  plant(plant, sheet, { from } = {}) {
    const spots = sheet.calloutsByKey.get(plant.key) || [];
    const drawn = spots.reduce((n, c) => n + c.count, 0);
    const zoneNames = [...new Set(spots.map((c) => sheet.zoneById.get(c.zoneId)?.name).filter(Boolean))];

    const collision = this.app.keyCollision(plant.key, sheet.id);
    const collisionFlag = collision ? `
      <p class="p-flag warn">On the ${esc(collision.sheetLabel)} sheet the same key
      <b>${esc(plant.key)}</b> means <i>${esc(collision.botanical)}</i> &mdash; a different plant.
      Keys are only meaningful within one sheet.</p>` : "";

    const inferred = spots.some((c) => c.inferred);
    const inferredFlag = inferred && spots[0]?.ambiguityNote
      ? `<p class="p-flag warn">${esc(spots[0].ambiguityNote)}</p>` : "";

    const gapFlag = plant.gap
      ? `<p class="p-flag warn">${esc(plant.gap.note)}</p>` : "";

    this.open(`
      ${from ? backBtn(from) : ""}
      <p class="p-eyebrow">${esc(sheet.label)} &middot; Key ${esc(plant.key)}</p>
      <h2 class="p-title">${esc(plant.common || plant.botanical)}</h2>
      <p class="p-bot">${esc(plant.botanical)}</p>
      ${photoFigure(plant)}
      ${collisionFlag}
      ${inferredFlag}
      ${gapFlag}

      <h3 class="p-sub">From the blueprint</h3>
      <dl class="p-facts">
        <dt>Key</dt><dd>${esc(plant.key)}</dd>
        <dt>Quantity</dt><dd>${plant.qty}</dd>
        <dt>Size</dt><dd>${esc(plant.size)}</dd>
        ${plant.remarks ? `<dt>Remarks</dt><dd>${esc(plant.remarks)}</dd>` : ""}
        <dt>Placed</dt><dd>${drawn} across ${spots.length} callout${spots.length === 1 ? "" : "s"}${
          plant.gap ? ` &mdash; ${plant.qty - drawn} not located` : ""}</dd>
      </dl>

      <h3 class="p-sub">Growing notes</h3>
      <dl class="p-facts">
        <dt>Type</dt><dd>${esc(plant.type)}${plant.evergreen === false ? ", deciduous" : plant.evergreen ? ", evergreen" : ""}</dd>
        <dt>Mature</dt><dd>${esc(plant.matureSize)}</dd>
        <dt>Sun</dt><dd>${esc(plant.sun)}</dd>
        <dt>Water</dt><dd>${esc(plant.water)}</dd>
        <dt>Bloom</dt><dd>${esc(plant.bloomSeason)}</dd>
      </dl>
      <p class="p-note">${esc(plant.note)}</p>
      <p class="p-note">Growing notes are added context, not part of the 2001 drawing.
        The blueprint only gives the four facts above it.</p>

      ${zoneNames.length ? `<h3 class="p-sub">Where it goes</h3>
        <ul class="chips">${zoneNames.map((n) => `<li class="chip">${esc(n)}</li>`).join("")}</ul>` : ""}

      <div class="p-actions">
        <button type="button" class="btn primary" data-act="locate" data-key="${esc(plant.key)}">
          Show all ${spots.length} location${spots.length === 1 ? "" : "s"}
        </button>
      </div>`);
  }

  callout(callout, sheet) {
    const zone = sheet.zoneById.get(callout.zoneId);
    const p = callout.plant;
    if (!p) {
      this.open(`
        <p class="p-eyebrow">${esc(sheet.label)}</p>
        <h2 class="p-title">Callout ${esc(callout.key)}</h2>
        <p class="p-flag warn">This key is not in the sheet's plant legend.</p>`);
      return;
    }

    this.open(`
      <p class="p-eyebrow">${esc(sheet.label)}${zone ? ` &middot; ${esc(zone.name)}` : ""}</p>
      <h2 class="p-title">${callout.count} &times; ${esc(p.common || p.botanical)}</h2>
      <p class="p-bot">${esc(p.botanical)}</p>
      ${photoFigure(p)}
      <dl class="p-facts">
        <dt>Here</dt><dd>${callout.count} plant${callout.count === 1 ? "" : "s"} at this spot</dd>
        <dt>Size</dt><dd>${esc(p.size)}</dd>
        ${p.remarks ? `<dt>Remarks</dt><dd>${esc(p.remarks)}</dd>` : ""}
        <dt>Sheet total</dt><dd>${p.qty} on the ${esc(sheet.label.toLowerCase())} plan</dd>
      </dl>
      <div class="p-actions">
        <button type="button" class="btn primary" data-act="plant" data-key="${esc(p.key)}">Full plant details</button>
        ${zone ? `<button type="button" class="btn" data-act="zone" data-zone="${esc(zone.id)}">${esc(zone.name)}</button>` : ""}
      </div>`);
  }

  areas(sheet) {
    const rows = sheet.zones.map((z) => {
      const n = z.plants.reduce((a, r) => a + r.count, 0);
      return `
        <li>
          <button type="button" class="arearow" data-act="zone" data-zone="${esc(z.id)}">
            <img src="${esc(asset(z.crop))}" alt="" loading="lazy" decoding="async">
            <span class="pmain">
              <span class="areaname">${esc(z.name)}</span>
              <span class="areameta">${n} plants &middot; ${z.plants.length} species</span>
            </span>
          </button>
        </li>`;
    }).join("");

    this.replace(`
      <p class="p-eyebrow">${esc(sheet.label)} &middot; sheet ${esc(sheet.sheetNumber)}</p>
      <h2 class="p-title">Garden areas</h2>
      <p class="p-blurb">${esc(sheet.description)}</p>
      <ul class="arealist">${rows}</ul>
      <p class="p-note">Area outlines are traced over a photograph of the paper plan and
        group the callouts belonging to each part of the garden. They are approximate.</p>`);
  }

  about(meta, sheets, credits) {
    const totals = sheets.map((s) =>
      `<dt>${esc(s.label)}</dt><dd>${s.plantTotal} plants, ${s.speciesCount} species (sheet ${esc(s.sheetNumber)})</dd>`
    ).join("");

    const creditList = Object.values(credits)
      .sort((a, b) => a.botanical.localeCompare(b.botanical))
      .map((c) => `<li><i>${esc(c.botanical)}</i> &mdash; ${esc(c.author)}, ${esc(c.licence)}
        (<a href="${esc(c.source)}" target="_blank" rel="noopener noreferrer">source</a>)</li>`)
      .join("");

    this.replace(`
      <p class="p-eyebrow">About</p>
      <h2 class="p-title">${esc(meta.project)}</h2>
      <p class="p-blurb">${esc(meta.address)}</p>

      <h3 class="p-sub">The drawing</h3>
      <dl class="p-facts">
        <dt>Designer</dt><dd>${esc(meta.designer)}</dd>
        <dt>Drawn</dt><dd>${esc(meta.date)}, revised ${esc(meta.revision)}</dd>
        <dt>By</dt><dd>${esc(meta.drawnBy)}</dd>
        <dt>Scale</dt><dd>${esc(meta.scale)}</dd>
        <dt>Job</dt><dd>${esc(meta.job)}</dd>
        ${totals}
      </dl>

      <p class="p-flag">${esc(meta.disclaimer)}</p>

      <h3 class="p-sub">Notes on the original sheet</h3>
      ${meta.planNotes.map((n) => `<p class="p-note">${esc(n)}</p>`).join("")}

      ${IS_BUNDLE ? `
        <h3 class="p-sub">This copy</h3>
        <p class="p-desc">You are looking at the single-file copy. Everything &mdash; both
          blueprints, every photo, all the data &mdash; is inside this one file, so it
          works with no signal at all. Keep it, or send it on to anyone.</p>`
      : `
        <h3 class="p-sub">Take it with you</h3>
        <p class="p-desc">The whole map also comes as one self-contained file. Nothing is
          fetched when you open it, so it works with no signal &mdash; useful at the far end
          of the garden &mdash; and you can email or AirDrop it to anyone who wants a copy.</p>
        <div class="p-actions">
          <a class="btn primary" href="${esc(OFFLINE_FILE)}" download>Download the offline copy</a>
        </div>`}

      <h3 class="p-sub">How to use it</h3>
      <p class="p-desc">Drag to pan and pinch or scroll to zoom. Tap a shaded area for the
        planting plan for that part of the garden, or tap a hexagon for the plant at that
        exact spot. The number in each hexagon is how many plants go there. Search accepts
        common names, botanical names, or the two-letter key from the legend.</p>

      <h3 class="p-sub">Where the information comes from</h3>
      <p class="p-note">${esc(meta.curatedFieldsNote)}</p>

      <h3 class="p-sub">Photo credits</h3>
      <ul class="credits">${creditList}</ul>

      <div class="p-actions">
        <button type="button" class="btn" data-act="areas">Browse garden areas</button>
      </div>`);
  }

  /* Let the sheet be flicked down on touch devices. */
  _dragToDismiss(grab) {
    let startY = null;
    grab.addEventListener("pointerdown", (e) => {
      startY = e.clientY;
      grab.setPointerCapture(e.pointerId);
      this.panel.style.transition = "none";
    });
    grab.addEventListener("pointermove", (e) => {
      if (startY == null) return;
      const dy = Math.max(0, e.clientY - startY);
      this.panel.style.transform = `translateY(${dy}px)`;
    });
    const end = (e) => {
      if (startY == null) return;
      const dy = Math.max(0, e.clientY - startY);
      startY = null;
      this.panel.style.transition = "";
      this.panel.style.transform = "";
      if (dy > 90) this.close();
    };
    grab.addEventListener("pointerup", end);
    grab.addEventListener("pointercancel", end);
  }
}

export { bboxOf };
