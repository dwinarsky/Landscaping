/* Editor mode (?edit=1).
 *
 * The area outlines are my tracing over a photograph of a paper plan, and the
 * callout positions come from shape detection. Both are close but neither is
 * authoritative, so this gives a way to correct them by dragging - on a phone
 * in the garden or on a laptop - and copy the fixed JSON back into the repo,
 * without needing to hand-edit coordinates.
 */

import { SVG_NS } from "./util.js";

export function isEditing() {
  return new URLSearchParams(location.search).get("edit") === "1";
}

export class Editor {
  constructor({ viewer, overlay, sheet, onChange }) {
    this.viewer = viewer;
    this.overlay = overlay;
    this.sheet = sheet;
    this.onChange = onChange || (() => {});
    this.layer = document.createElementNS(SVG_NS, "g");
    this.layer.setAttribute("id", "edit-layer");
    overlay.append(this.layer);
    this._buildBar();
    this.render();
  }

  render() {
    this.layer.replaceChildren();
    for (const zone of this.sheet.zones) {
      zone.polygon.forEach((pt, i) => this.layer.append(this._handle(pt, "zone", zone, i)));
    }
    for (const c of this.sheet.callouts) {
      this.layer.append(this._handle([c.x, c.y], "callout", c, null));
    }
  }

  _handle(pt, kind, owner, index) {
    const g = document.createElementNS(SVG_NS, "g");
    g.setAttribute("class", "mk");
    g.setAttribute("transform", `translate(${pt[0]} ${pt[1]})`);

    const dot = document.createElementNS(SVG_NS, "circle");
    dot.setAttribute("r", kind === "zone" ? 9 : 7);
    dot.setAttribute("fill", kind === "zone" ? "#e0563f" : "#2fae6a");
    dot.setAttribute("stroke", "#fff");
    dot.setAttribute("stroke-width", "1.5");
    dot.style.cursor = "grab";
    g.append(dot);

    let dragging = false;
    dot.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      dragging = true;
      dot.setPointerCapture(e.pointerId);
    });
    dot.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      e.stopPropagation();
      const { x, y } = this.viewer.toSheet(e.clientX, e.clientY);
      const nx = Math.round(x);
      const ny = Math.round(y);
      g.setAttribute("transform", `translate(${nx} ${ny})`);
      if (kind === "zone") owner.polygon[index] = [nx, ny];
      else { owner.x = nx; owner.y = ny; }
    });
    const stop = (e) => {
      if (!dragging) return;
      e.stopPropagation();
      dragging = false;
      this.onChange();
      this._status("edited - remember to copy the JSON");
    };
    dot.addEventListener("pointerup", stop);
    dot.addEventListener("pointercancel", stop);
    return g;
  }

  _buildBar() {
    const bar = document.createElement("div");
    bar.id = "editbar";
    bar.innerHTML = `
      <span class="eb-tag">EDIT MODE</span>
      <button type="button" class="btn" data-copy="zones">Copy zones.json</button>
      <button type="button" class="btn" data-copy="callouts">Copy callouts.json</button>
      <span class="eb-status"></span>`;
    Object.assign(bar.style, {
      position: "fixed", left: "10px", bottom: "10px", zIndex: 60,
      display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap",
      padding: "8px 10px", borderRadius: "10px",
      background: "var(--card)", border: "1px solid var(--line)",
      boxShadow: "var(--shadow-1)", font: "500 12px var(--sans)",
      maxWidth: "calc(100vw - 20px)",
    });
    bar.querySelector(".eb-tag").style.cssText =
      "font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:#e0563f";
    document.body.append(bar);
    this.bar = bar;

    bar.addEventListener("click", async (e) => {
      const which = e.target.closest("[data-copy]")?.dataset.copy;
      if (!which) return;
      const text = which === "zones" ? this._zonesJson() : this._calloutsJson();
      try {
        await navigator.clipboard.writeText(text);
        this._status(`${which}.json copied`);
      } catch {
        // Clipboard needs a secure context; fall back to something usable.
        const w = window.open("", "_blank");
        if (w) { w.document.body.style.cssText = "white-space:pre;font:12px monospace"; w.document.body.textContent = text; }
        this._status("clipboard blocked - opened in a new tab");
      }
    });
  }

  _status(msg) {
    const s = this.bar.querySelector(".eb-status");
    s.textContent = msg;
    s.style.color = "var(--text-dim)";
  }

  _zonesJson() {
    const out = this.sheet.zones.map((z) => ({
      id: z.id, name: z.name, blurb: z.blurb, description: z.description,
      existing: z.existing, polygon: z.polygon,
    }));
    return JSON.stringify(out, null, 2) + "\n";
  }

  _calloutsJson() {
    const out = this.sheet.callouts.map((c) => {
      const rec = { id: c.id, key: c.key, count: c.count, x: c.x, y: c.y };
      if (c.bbox) rec.bbox = c.bbox;
      if (c.candidate != null) rec.candidate = c.candidate;
      if (c.resolvedKey) rec.resolvedKey = c.resolvedKey;
      if (c.inferred) rec.inferred = c.inferred;
      if (c.ambiguityNote) rec.ambiguityNote = c.ambiguityNote;
      if (c.note) rec.note = c.note;
      return rec;
    });
    return JSON.stringify(out, null, 1) + "\n";
  }

  destroy() {
    this.layer.remove();
    this.bar.remove();
  }
}
