/* The tappable layer: zone outlines and one marker per plant callout.
 *
 * Both live in the SVG overlay in sheet coordinates, so the browser does the
 * hit-testing. Marker children are counter-scaled by --inv (set by the viewer)
 * so a dot stays a constant size on screen at any zoom, and detail is revealed
 * progressively - dots only when zoomed out, plant keys once you are in close.
 */

import { svgEl } from "./util.js";

export class Hotspots {
  constructor({ overlay, zoneLayer, markerLayer, onZone, onCallout }) {
    this.overlay = overlay;
    this.zoneLayer = zoneLayer;
    this.markerLayer = markerLayer;
    this.onZone = onZone;
    this.onCallout = onCallout;
    this.zoneNodes = new Map();
    this.markerNodes = new Map();
  }

  render(sheet) {
    this.zoneLayer.replaceChildren();
    this.markerLayer.replaceChildren();
    this.zoneNodes.clear();
    this.markerNodes.clear();

    for (const zone of sheet.zones) {
      const poly = svgEl("polygon", {
        class: "zone",
        points: zone.polygon.map((p) => p.join(",")).join(" "),
        role: "button",
        tabindex: "0",
        "aria-label": `${zone.name}, ${zone.callouts.length} plant callouts`,
      });
      poly.addEventListener("click", () => this.onZone(zone));
      poly.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.onZone(zone); }
      });
      this.zoneLayer.append(poly);

      const label = svgEl("text", {
        class: "zone-label",
        x: zone.centroid[0],
        y: zone.centroid[1],
      });
      label.textContent = zone.name;
      this.zoneLayer.append(label);
      this.zoneNodes.set(zone.id, poly);
    }

    for (const c of sheet.callouts) {
      const g = svgEl("g", {
        class: "mk",
        transform: `translate(${c.x} ${c.y})`,
        role: "button",
        tabindex: "0",
        "aria-label": c.plant
          ? `${c.count} ${c.plant.common || c.plant.botanical}`
          : `${c.count} of ${c.key}`,
      });
      g.append(svgEl("circle", { class: "mk-hit", r: 22 }));
      g.append(svgEl("circle", { class: "mk-dot", r: 11 }));

      const n = svgEl("text", { class: "mk-n", x: 0, y: 0 });
      n.textContent = c.count;
      g.append(n);

      const key = svgEl("text", { class: "mk-key", x: 0, y: 24 });
      key.textContent = c.lookupKey;
      g.append(key);

      g.addEventListener("click", () => this.onCallout(c));
      g.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.onCallout(c); }
      });
      this.markerLayer.append(g);
      this.markerNodes.set(c.id, g);
    }
  }

  /** Reveal more detail as the plan is zoomed in. */
  setDetail(relativeScale) {
    const level = relativeScale > 3.2 ? "high" : relativeScale > 1.7 ? "mid" : "low";
    this.overlay.dataset.detail = level;
  }

  activeZone(zoneId) {
    for (const [id, node] of this.zoneNodes) node.classList.toggle("is-active", id === zoneId);
  }

  activeCallout(calloutId) {
    for (const [id, node] of this.markerNodes) node.classList.toggle("is-active", id === calloutId);
  }

  /** Flash every marker for one species, so you can see where they all go. */
  light(calloutIds) {
    for (const node of this.markerNodes.values()) node.classList.remove("is-lit");
    // Force a reflow so re-lighting the same set restarts the animation.
    void this.markerLayer.getBoundingClientRect();
    for (const id of calloutIds) this.markerNodes.get(id)?.classList.add("is-lit");
  }

  clearLit() {
    for (const node of this.markerNodes.values()) node.classList.remove("is-lit");
  }
}
