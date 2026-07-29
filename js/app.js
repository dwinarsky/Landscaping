/* Bootstrap and the wiring between map, panel and URL. */

import { loadPlan, asset, bboxOf } from "./data.js";
import { Viewer } from "./viewer.js";
import { Hotspots } from "./hotspots.js";
import { Panel } from "./panel.js";
import { Search } from "./search.js";
import { Editor, isEditing } from "./editor.js";

const $ = (sel) => document.querySelector(sel);

class App {
  async start() {
    this.plan = await loadPlan();
    this.sheet = null;
    this.showingFullSheet = false;

    this.viewer = new Viewer({
      map: $("#map"),
      stage: $("#stage"),
      img: $("#plan-img"),
      overlay: $("#overlay"),
      onScale: (_s, rel) => this.hotspots.setDetail(rel),
    });

    this.hotspots = new Hotspots({
      overlay: $("#overlay"),
      zoneLayer: $("#zone-layer"),
      markerLayer: $("#marker-layer"),
      onZone: (z) => { if (!this.viewer.suppressClick) this.showZone(z.id); },
      onCallout: (c) => { if (!this.viewer.suppressClick) this.showCallout(c); },
    });

    this.panel = new Panel({
      panel: $("#panel"), body: $("#panel-body"),
      grab: $("#panel-grab"), scrim: $("#scrim"), app: this,
    });

    this.search = new Search({
      button: $("#btn-search"), bar: $("#searchbar"),
      input: $("#search-input"), results: $("#search-results"), app: this,
    });

    this._applyIdentity();
    this._buildSheetPicker();
    this._bindControls();

    const params = new URLSearchParams(location.search);
    const startSheet = params.get("sheet");
    const initial = this.plan.sheets.find((s) => s.id === startSheet) || this.plan.sheets[0];
    await this.setSheet(initial.id, { fromUrl: true });

    const zone = params.get("zone");
    const key = params.get("plant");
    if (zone && this.sheet.zoneById.has(zone)) this.showZone(zone, { frame: true });
    else if (key && this.sheet.plantByKey.has(key)) this.showPlant(key);

    if (isEditing()) this._startEditor();
  }

  /** Whose plan this is comes from the data, not from index.html.
   *  On the locked deploy index.html is served in the clear, so it must not
   *  name the property; the header and tab title are filled in here once the
   *  plan has actually been decrypted. */
  _applyIdentity() {
    const { project, address } = this.plan.meta;
    $("#topbar-project").textContent = project;
    $("#topbar-addr").textContent = address;
    document.title = `${project} — ${address}`;
  }

  /* ------------------------------------------------------------- sheets */

  _buildSheetPicker() {
    const wrap = $(".sheetpick");
    wrap.replaceChildren();
    for (const s of this.plan.sheets) {
      const b = document.createElement("button");
      b.type = "button";
      b.role = "tab";
      b.textContent = s.label;
      b.dataset.sheet = s.id;
      b.setAttribute("aria-selected", "false");
      b.addEventListener("click", () => this.setSheet(s.id));
      wrap.append(b);
    }
  }

  async setSheet(id, { fromUrl = false } = {}) {
    const sheet = this.plan.sheets.find((s) => s.id === id);
    if (!sheet || sheet === this.sheet) return;
    this.sheet = sheet;

    for (const b of document.querySelectorAll(".sheetpick button")) {
      b.setAttribute("aria-selected", String(b.dataset.sheet === id));
    }

    const img = $("#plan-img");
    img.alt = `${sheet.title}, ${this.plan.meta.designer}, sheet ${sheet.sheetNumber}`;
    img.width = sheet.width;
    img.height = sheet.height;
    // Pick the raster here rather than leaving it to srcset. The image is sized
    // in sheet pixels and then CSS-transform scaled, so the browser has no way
    // to work out how large it will actually be drawn, and `sizes` guesses wrong.
    img.src = asset(`${sheet.plan}-${this._bestVariant(sheet)}.webp`);
    img.removeAttribute("srcset");
    img.removeAttribute("sizes");

    this.viewer.setSheet(sheet);
    this.hotspots.render(sheet);
    this.viewer.measureFit();
    this.showingFullSheet = false;
    $("#btn-full").setAttribute("aria-pressed", "false");
    this.viewer.frame(sheet.defaultView);
    this.panel.close();

    const hint = $("#hint");
    hint.hidden = false;
    hint.textContent = sheet.mapped
      ? "Tap an area of the plan, or a hexagon, to see what is planted there."
      : `${sheet.label}: the legend is searchable, but the callouts on this sheet `
        + "have not been mapped yet. Pinch to read the drawing.";

    if (this.editor) { this.editor.destroy(); this._startEditor(); }
    if (!fromUrl) this._syncUrl({});
  }

  /** Largest raster worth downloading for this screen. */
  _bestVariant(sheet) {
    const variants = (sheet.variants || [2048]).slice().sort((a, b) => a - b);
    const budget = Math.min(window.screen?.width || 1280, 1600)
      * Math.min(window.devicePixelRatio || 1, 3) * 3.5;
    return variants.find((w) => w >= budget) ?? variants[variants.length - 1];
  }

  /* -------------------------------------------------------------- views */

  showZone(zoneId, { frame = false } = {}) {
    const zone = this.sheet.zoneById.get(zoneId);
    if (!zone) return;
    this.hotspots.activeZone(zoneId);
    this.hotspots.activeCallout(null);
    this.hotspots.clearLit();
    this.panel.zone(zone, this.sheet);
    this._hideHint();
    if (frame) this.frameZone(zoneId);
    this._syncUrl({ zone: zoneId });
  }

  frameZone(zoneId) {
    const zone = this.sheet.zoneById.get(zoneId);
    if (!zone) return;
    this.viewer.frame(bboxOf(zone.polygon), { padding: 0.1, animate: true });
  }

  showCallout(callout) {
    this.hotspots.activeCallout(callout.id);
    this.hotspots.activeZone(callout.zoneId);
    this.hotspots.clearLit();
    this.panel.callout(callout, this.sheet);
    this._hideHint();
  }

  showPlant(key) {
    const plant = this.sheet.plantByKey.get(key);
    if (!plant) return;
    const from = this.panel.stack.length > 1 ? "Back" : null;
    this.panel.plant(plant, this.sheet, { from });
    this._syncUrl({ plant: key });
  }

  async showPlantOnSheet(sheetId, key) {
    if (sheetId !== this.sheet.id) await this.setSheet(sheetId);
    this.showPlant(key);
    this.locateSpecies(key, { quiet: true });
  }

  /** Flash every marker for a species and frame them all. */
  locateSpecies(key, { quiet = false } = {}) {
    const spots = this.sheet.calloutsByKey.get(key) || [];
    if (!spots.length) return;
    this.hotspots.light(spots.map((c) => c.id));
    if (spots.length === 1) {
      this.viewer.centerOn(spots[0].x, spots[0].y, Math.max(this.viewer.scale, this.viewer.fitScale * 3.4));
    } else {
      const xs = spots.map((c) => c.x);
      const ys = spots.map((c) => c.y);
      this.viewer.frame({
        x: Math.min(...xs) - 90, y: Math.min(...ys) - 90,
        width: Math.max(...xs) - Math.min(...xs) + 180,
        height: Math.max(...ys) - Math.min(...ys) + 180,
      }, { padding: 0.06, animate: true });
    }
    if (!quiet) this._hideHint();
  }

  showAreas() {
    this.panel.areas(this.sheet);
    this.hotspots.activeZone(null);
    this.hotspots.activeCallout(null);
    $("#btn-areas").setAttribute("aria-expanded", "true");
  }

  showAbout() {
    this.panel.about(this.plan.meta, this.plan.sheets, this.plan.credits);
  }

  clearSelection() {
    this.hotspots.activeZone(null);
    this.hotspots.activeCallout(null);
    this.hotspots.clearLit();
    $("#btn-areas").setAttribute("aria-expanded", "false");
    this._syncUrl({});
  }

  /** The same key on the other sheet, when it means a different plant. */
  keyCollision(key, sheetId) {
    for (const other of this.plan.sheets) {
      if (other.id === sheetId) continue;
      const p = other.plantByKey.get(key);
      const mine = this.plan.sheets.find((s) => s.id === sheetId)?.plantByKey.get(key);
      if (p && mine && p.botanical !== mine.botanical) {
        return { sheetLabel: other.label, botanical: p.botanical, sheetId: other.id };
      }
    }
    return null;
  }

  /* ----------------------------------------------------------- plumbing */

  _bindControls() {
    $("#btn-zoomin").addEventListener("click", () => this.viewer.zoomBy(1.6, null, null, true));
    $("#btn-zoomout").addEventListener("click", () => this.viewer.zoomBy(1 / 1.6, null, null, true));
    $("#btn-fit").addEventListener("click", () => {
      this.showingFullSheet = false;
      $("#btn-full").setAttribute("aria-pressed", "false");
      this.viewer.frame(this.sheet.defaultView, { animate: true });
    });
    $("#btn-full").addEventListener("click", () => {
      this.showingFullSheet = !this.showingFullSheet;
      $("#btn-full").setAttribute("aria-pressed", String(this.showingFullSheet));
      if (this.showingFullSheet) this.viewer.fitAll({ animate: true });
      else this.viewer.frame(this.sheet.defaultView, { animate: true });
    });
    $("#btn-areas").addEventListener("click", () => {
      if ($("#btn-areas").getAttribute("aria-expanded") === "true") this.panel.close();
      else this.showAreas();
    });
    $("#btn-about").addEventListener("click", () => this.showAbout());

    // A tap on empty paper dismisses whatever is open.
    $("#map").addEventListener("click", (e) => {
      if (this.viewer.suppressClick) return;
      if (e.target.closest(".zone, .mk, .mapctl, .hint")) return;
      if (this.panel.isOpen()) this.panel.close();
    });
  }

  _hideHint() {
    const hint = $("#hint");
    if (!hint.hidden) hint.hidden = true;
  }

  _syncUrl({ zone, plant }) {
    const p = new URLSearchParams();
    if (this.sheet) p.set("sheet", this.sheet.id);
    if (zone) p.set("zone", zone);
    if (plant) p.set("plant", plant);
    if (isEditing()) p.set("edit", "1");
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  _startEditor() {
    this.editor = new Editor({
      viewer: this.viewer,
      overlay: $("#overlay"),
      sheet: this.sheet,
      onChange: () => {},
    });
  }
}

const app = new App();
app.start().catch((err) => {
  console.error(err);
  document.body.insertAdjacentHTML("afterbegin",
    `<p style="position:fixed;inset:auto 12px 12px;z-index:99;margin:0;padding:12px 14px;
       background:#fff;color:#8c2f20;border:1px solid #e0b9b1;border-radius:10px;
       font:14px/1.5 system-ui">Could not load the plan data: ${err.message}.
       If you opened this file directly, serve the folder over HTTP instead
       (<code>python3 -m http.server</code>).</p>`);
});
