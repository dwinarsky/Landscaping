/* Small helpers shared across modules.
 *
 * These live here rather than being repeated per module so the single-file
 * bundle can concatenate everything into one scope without redeclaring them.
 */

export const SVG_NS = "http://www.w3.org/2000/svg";

/** Escape text for interpolation into an HTML template string. */
export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

/** Create an SVG element with attributes. */
export function svgEl(name, attrs = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}
