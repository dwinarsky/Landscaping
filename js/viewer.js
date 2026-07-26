/* Pan and zoom over the plan.
 *
 * The stage holds the plan image and an SVG overlay, both sized in *sheet
 * pixels* - the coordinate space the rectified scan defines and that every
 * zone polygon and callout position is recorded in. A single CSS transform on
 * the stage does all the panning and zooming, which keeps hit-testing free:
 * the SVG shapes receive pointer events directly, already in sheet coordinates.
 */

const MAX_SCALE = 14;

export class Viewer {
  constructor({ map, stage, img, overlay, onScale }) {
    this.map = map;
    this.stage = stage;
    this.img = img;
    this.overlay = overlay;
    this.onScale = onScale || (() => {});

    this.sheetW = 1;
    this.sheetH = 1;
    this.scale = 1;
    this.fitScale = 1;
    this.tx = 0;
    this.ty = 0;

    this.pointers = new Map();
    this.pinch = null;
    this.moved = false;
    this.suppressClick = false;

    this._bind();
  }

  setSheet({ width, height }) {
    this.sheetW = width;
    this.sheetH = height;
    this.stage.style.width = `${width}px`;
    this.stage.style.height = `${height}px`;
    this.overlay.setAttribute("viewBox", `0 0 ${width} ${height}`);
  }

  viewport() {
    const r = this.map.getBoundingClientRect();
    return { w: r.width, h: r.height, left: r.left, top: r.top };
  }

  /** Frame a rect given in sheet coordinates. */
  frame(rect, { padding = 0.04, animate = false } = {}) {
    const { w, h } = this.viewport();
    const pad = 1 + padding * 2;
    const s = Math.min(w / (rect.width * pad), h / (rect.height * pad));
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;
    this._apply(s, w / 2 - cx * s, h / 2 - cy * s, animate);
  }

  /** Whole-sheet fit, and remember it as the reference zoom level. */
  fitAll({ animate = false } = {}) {
    const { w, h } = this.viewport();
    this.fitScale = Math.min(w / this.sheetW, h / this.sheetH);
    this.frame({ x: 0, y: 0, width: this.sheetW, height: this.sheetH }, { animate });
  }

  /** Remember the fit-to-whole-sheet scale without moving there. */
  measureFit() {
    const { w, h } = this.viewport();
    this.fitScale = Math.min(w / this.sheetW, h / this.sheetH);
  }

  centerOn(x, y, scale, { animate = true } = {}) {
    const { w, h } = this.viewport();
    const s = this._clampScale(scale ?? this.scale);
    this._apply(s, w / 2 - x * s, h / 2 - y * s, animate);
  }

  zoomBy(factor, cx, cy, animate = false) {
    const { w, h, left, top } = this.viewport();
    const px = cx == null ? w / 2 : cx - left;
    const py = cy == null ? h / 2 : cy - top;
    const s = this._clampScale(this.scale * factor);
    const k = s / this.scale;
    this._apply(s, px - (px - this.tx) * k, py - (py - this.ty) * k, animate);
  }

  toSheet(clientX, clientY) {
    const { left, top } = this.viewport();
    return {
      x: (clientX - left - this.tx) / this.scale,
      y: (clientY - top - this.ty) / this.scale,
    };
  }

  _clampScale(s) {
    return Math.min(MAX_SCALE, Math.max(this.fitScale * 0.85, s));
  }

  /** Keep at least a slice of the sheet on screen so it can't be lost. */
  _clampPan(tx, ty, s) {
    const { w, h } = this.viewport();
    const pw = this.sheetW * s;
    const ph = this.sheetH * s;
    const slackX = Math.min(w * 0.5, pw * 0.5);
    const slackY = Math.min(h * 0.5, ph * 0.5);
    if (pw <= w) tx = (w - pw) / 2;
    else tx = Math.min(slackX, Math.max(w - pw - slackX, tx));
    if (ph <= h) ty = (h - ph) / 2;
    else ty = Math.min(slackY, Math.max(h - ph - slackY, ty));
    return [tx, ty];
  }

  _apply(s, tx, ty, animate) {
    this.scale = s;
    [this.tx, this.ty] = this._clampPan(tx, ty, s);
    this.stage.style.transition = animate
      ? "transform 340ms cubic-bezier(.22,.68,.24,1)"
      : "none";
    this.stage.style.transform =
      `translate(${this.tx}px, ${this.ty}px) scale(${this.scale})`;
    this.overlay.style.setProperty("--inv", 1 / this.scale);
    this.onScale(this.scale, this.scale / (this.fitScale || 1));
  }

  _bind() {
    const map = this.map;

    map.addEventListener("pointerdown", (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      // The controls sit inside the map for positioning. Capturing the pointer
      // here would retarget the following click to the map, so the buttons
      // would never fire - leave chrome alone and only pan from the plan.
      if (e.target.closest(".mapctl, .hint")) return;
      map.setPointerCapture(e.pointerId);
      this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      this.moved = false;
      if (this.pointers.size === 2) {
        const [a, b] = [...this.pointers.values()];
        this.pinch = {
          dist: Math.hypot(a.x - b.x, a.y - b.y),
          scale: this.scale,
          mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
        };
      }
      map.classList.add("dragging");
    });

    map.addEventListener("pointermove", (e) => {
      const p = this.pointers.get(e.pointerId);
      if (!p) return;
      const dx = e.clientX - p.x;
      const dy = e.clientY - p.y;
      p.x = e.clientX;
      p.y = e.clientY;

      if (this.pointers.size >= 2 && this.pinch) {
        const [a, b] = [...this.pointers.values()];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (this.pinch.dist > 0) {
          const target = this.pinch.scale * (dist / this.pinch.dist);
          const { left, top } = this.viewport();
          const mx = (a.x + b.x) / 2 - left;
          const my = (a.y + b.y) / 2 - top;
          const s = this._clampScale(target);
          const k = s / this.scale;
          this._apply(s, mx - (mx - this.tx) * k, my - (my - this.ty) * k, false);
        }
        this.moved = true;
        return;
      }

      if (Math.abs(dx) + Math.abs(dy) > 2) this.moved = true;
      this._apply(this.scale, this.tx + dx, this.ty + dy, false);
    });

    const release = (e) => {
      this.pointers.delete(e.pointerId);
      if (this.pointers.size < 2) this.pinch = null;
      if (this.pointers.size === 0) {
        map.classList.remove("dragging");
        // A drag must not also register as a tap on whatever is underneath.
        this.suppressClick = this.moved;
        setTimeout(() => { this.suppressClick = false; }, 0);
      }
    };
    map.addEventListener("pointerup", release);
    map.addEventListener("pointercancel", release);

    map.addEventListener("wheel", (e) => {
      e.preventDefault();
      // Trackpad pinch arrives as ctrl+wheel; give it a finer step.
      const step = e.ctrlKey ? 0.012 : 0.0022;
      this.zoomBy(Math.exp(-e.deltaY * step), e.clientX, e.clientY, false);
    }, { passive: false });

    map.addEventListener("dblclick", (e) => {
      e.preventDefault();
      this.zoomBy(2, e.clientX, e.clientY, true);
    });

    window.addEventListener("resize", () => {
      const prev = this.fitScale;
      this.measureFit();
      if (Math.abs(this.scale - prev) < 1e-6) this.fitAll();
      else this._apply(this.scale, this.tx, this.ty, false);
    });
  }
}
