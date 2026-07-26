/* Search across both sheets at once.
 *
 * Matches common name, botanical name and the two-letter legend key. Results
 * are labelled with which yard they are in, because the same key means
 * different plants on the two sheets and a bare "AA" result would be ambiguous.
 */

import { esc } from "./util.js";

function score(plant, q) {
  const key = plant.key.toLowerCase();
  const common = (plant.common || "").toLowerCase();
  const bot = plant.botanical.toLowerCase();

  if (key === q) return 100;
  if (common.startsWith(q)) return 80;
  if (bot.startsWith(q)) return 70;
  if (common.includes(q)) return 55;
  if (bot.includes(q)) return 45;
  if ((plant.type || "").startsWith(q)) return 20;
  if ((plant.remarks || "").toLowerCase().includes(q)) return 15;
  return 0;
}

export class Search {
  constructor({ button, bar, input, results, app }) {
    this.bar = bar;
    this.input = input;
    this.results = results;
    this.app = app;
    this.button = button;

    button.addEventListener("click", () => this.toggle());

    input.addEventListener("input", () => this.run());
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") this.toggle(false);
      if (e.key === "Enter") this.results.querySelector(".sres")?.click();
    });

    results.addEventListener("click", (e) => {
      const btn = e.target.closest(".sres");
      if (!btn) return;
      this.app.showPlantOnSheet(btn.dataset.sheet, btn.dataset.key);
      this.toggle(false);
    });
  }

  toggle(force) {
    const open = force ?? this.bar.hidden;
    this.bar.hidden = !open;
    this.button.setAttribute("aria-expanded", String(open));
    if (open) this.input.focus();
    else { this.input.value = ""; this.results.replaceChildren(); }
  }

  run() {
    const q = this.input.value.trim().toLowerCase();
    if (q.length < 1) { this.results.replaceChildren(); return; }

    const hits = [];
    for (const sheet of this.app.plan.sheets) {
      for (const plant of sheet.plants) {
        const s = score(plant, q);
        if (s > 0) hits.push({ s, plant, sheet });
      }
    }
    hits.sort((a, b) => b.s - a.s || (a.plant.common || "").localeCompare(b.plant.common || ""));

    if (!hits.length) {
      this.results.innerHTML = `<p class="searchempty">Nothing matches &ldquo;${esc(q)}&rdquo;.</p>`;
      return;
    }

    this.results.innerHTML = hits.slice(0, 24).map(({ plant, sheet }) => `
      <button type="button" class="sres" data-sheet="${esc(sheet.id)}" data-key="${esc(plant.key)}">
        <span class="pkey">${esc(plant.key)}</span>
        <span class="sres-txt">
          <span class="sres-common">${esc(plant.common || plant.botanical)}</span>
          <span class="sres-bot">${esc(plant.botanical)}</span>
        </span>
        <span class="sres-meta">${esc(sheet.label)}<br>${plant.qty} &times; ${esc(plant.size)}</span>
      </button>`).join("");
  }
}
