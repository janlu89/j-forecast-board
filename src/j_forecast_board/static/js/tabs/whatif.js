// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { C, label, layout, line, PCONF, unitAxis, vline } from "../core/charts.js";
import { $, $$, esc } from "../core/dom.js";
import { chip, dur, fmt, spct } from "../core/format.js";
import { common, ds, S } from "../core/state.js";
import { withBusy } from "../core/ui.js";

export const WI_PRESETS = {
  bike: [
    { label: "🌧 Rainy first week", edits: { "Weather (1 clear … 4 storm)": { mode: "set", value: 3, start: 0, end: 7 } } },
    { label: "☀ Clear skies", edits: { "Weather (1 clear … 4 storm)": { mode: "set", value: 1 } } },
    { label: "🔥 Heatwave +8 °C", edits: { "Temperature °C": { mode: "shift", value: 8 } } },
    { label: "❄ Cold snap −8 °C", edits: { "Temperature °C": { mode: "shift", value: -8 } } },
    { label: "🎉 Holiday week", edits: { Holiday: { mode: "set", value: 1, start: 0, end: 7 }, "Working day": { mode: "set", value: 0, start: 0, end: 7 } } },
  ],
  rossmann: [
    { label: "🏷 Promo every weekday", edits: { Promo: { mode: "set", value: 1 } } },
    { label: "🚫 No promotions", edits: { Promo: { mode: "set", value: 0 } } },
    { label: "🎒 School holidays all period", edits: { "School holiday": { mode: "set", value: 1 } } },
    { label: "🔒 Closed first week", edits: { Open: { mode: "set", value: 0, start: 0, end: 7 } } },
  ],
};
export function initWhatIf() {
  $("#wiRun").onclick = () => runWhatIf(false);
  $("#wiReset").onclick = () => { $$(".wi-row .mode").forEach((m) => (m.value = "keep")); runWhatIf(false); };
}
export function readEdits() {
  return $$(".wi-row").map((row) => ({ name: row.dataset.name, mode: row.querySelector(".mode").value, value: +row.querySelector(".val").value,
    start: +row.querySelector(".from").value, end: +row.querySelector(".to").value })).filter((e) => e.mode !== "keep");
}
export async function runWhatIf(initial) {
  S.dirty.whatif = false;
  const d = ds();
  if (!d.has_known) {
    $("#wiRows").innerHTML = `<div class="empty">“${esc(d.name)}” has no covariates known in advance.<br>Try <b>Rossmann</b> or <b>Bike sharing</b>, or load your own data with e.g. promotions or prices as <i>known</i> columns.</div>`;
    $("#wiPresets").innerHTML = ""; $("#wiChips").innerHTML = ""; Plotly.purge("wiPlot"); Plotly.purge("wiCov"); return;
  }
  await withBusy($("#wiPlotCard"), async () => {
    const edits = initial || !S.wi ? [] : readEdits();
    const r = await api("api/whatif", common({ edits }));
    if (initial || !S.wi) buildWhatIfRows(r);
    S.wi = r; renderWhatIf(r);
  });
}
export function buildWhatIfRows(r) {
  const H = r.horizon;
  $("#wiRows").innerHTML = r.covariates.map((c) => `<div class="wi-row" data-name="${esc(c.name)}"><span class="nm">${esc(c.name)}</span>
    <select class="mode"><option value="keep">keep</option><option value="set">set to</option>${c.cat ? "" : '<option value="shift">shift by</option><option value="scale">scale ×</option>'}</select>
    ${c.cat ? `<select class="val">${c.levels.map((l) => `<option>${l}</option>`).join("")}</select>` : '<input type="number" class="val" step="any" value="0">'}
    <span class="rng">steps <input type="number" class="from" value="0" min="0" max="${H}"> to <input type="number" class="to" value="${H}" min="1" max="${H}">
    <span class="note">range ${fmt(c.vmin)} … ${fmt(c.vmax)}</span></span></div>`).join("");
  const presets = WI_PRESETS[r.meta.key] || r.covariates.flatMap((c) => c.cat
    ? (c.levels.length === 2 ? [{ label: `${c.name} = ${c.levels[1]}`, edits: { [c.name]: { mode: "set", value: c.levels[1] } } }, { label: `${c.name} = ${c.levels[0]}`, edits: { [c.name]: { mode: "set", value: c.levels[0] } } }] : [])
    : [{ label: `${c.name} +20%`, edits: { [c.name]: { mode: "scale", value: 1.2 } } }, { label: `${c.name} −20%`, edits: { [c.name]: { mode: "scale", value: 0.8 } } }]);
  $("#wiPresets").innerHTML = presets.map((p, i) => `<button data-p="${i}">${esc(p.label)}</button>`).join("");
  $$("#wiPresets button").forEach((b) => (b.onclick = () => {
    const p = presets[+b.dataset.p];
    $$(".wi-row").forEach((row) => {
      const e = p.edits[row.dataset.name];
      row.querySelector(".mode").value = e ? e.mode : "keep";
      if (e) { row.querySelector(".val").value = e.value; row.querySelector(".from").value = e.start ?? 0; row.querySelector(".to").value = e.end ?? H; }
    });
    runWhatIf(false);
  }));
}
/** Base vs scenario chart of an api/whatif result (also used by the chat). */
export function drawWhatIf(el, r, extra = {}) {
  const last = r.dates.length - 1, fx = [r.dates[last], ...r.future_dates], j = (a) => [r.y[last], ...a];
  const changed = JSON.stringify(r.base.median) !== JSON.stringify(r.scenario.median);
  const tr = [line(r.dates, r.y, C.white, "actual", { line: { width: 1.2 } }), ...band(fx, j(r.base.lo), j(r.base.hi), C.green, "base 80%", 0.16),
    line(fx, j(r.base.median), C.green, "base forecast", { line: { width: 2 } })];
  if (changed) tr.push(...band(fx, j(r.scenario.lo), j(r.scenario.hi), C.purple, "scenario 80%", 0.2), line(fx, j(r.scenario.median), C.purple, "scenario", { line: { width: 2.2 } }));
  Plotly.react(el, tr, layout({ shapes: [vline(r.dates[last], C.green)], annotations: [label(r.dates[last], "future", C.green)], yaxis: unitAxis(r.meta.unit), ...extra }), PCONF);
}
export function renderWhatIf(r) {
  const last = r.dates.length - 1;
  drawWhatIf("wiPlot", r);
  const t = r.totals;
  $("#wiChips").innerHTML = [chip(r.meta.n > 1 ? r.meta.id_label : "Series", `#${esc(r.id)}`), chip("Total over horizon · base", fmt(t.base)), chip("Scenario", fmt(t.scenario)),
    chip("Difference", `${t.delta >= 0 ? "+" : ""}${fmt(t.delta)} (${spct(t.pct)})`, t.delta > 0 ? "good" : t.delta < 0 ? "bad" : ""), chip("Compute", dur(r.seconds))].join("");
  const n = r.covariates.length, gap = 0.06, h = (1 - gap * (n - 1)) / n, ct = [], ann = [];
  const lay = layout({ margin: { l: 130, r: 18, t: 8, b: 30 }, showlegend: false });
  r.covariates.forEach((c, i) => {
    const ax = i === 0 ? "" : String(i + 1), y0 = 1 - (i + 1) * h - i * gap, sh = c.cat ? "hv" : "linear";
    lay[`yaxis${ax}`] = { domain: [y0, y0 + h], gridcolor: C.grid, zeroline: false, fixedrange: true, nticks: 3, showticklabels: !c.cat };
    ct.push({ x: r.dates, y: c.hist, mode: "lines", line: { color: C.grey, width: 1, shape: sh }, xaxis: "x", yaxis: `y${ax}`, name: "history" });
    ct.push({ x: r.future_dates, y: c.base, mode: "lines", line: { color: C.green, width: 1.6, shape: sh }, xaxis: "x", yaxis: `y${ax}`, name: "base" });
    ct.push({ x: r.future_dates, y: c.scenario, mode: "lines", line: { color: C.purple, width: 1.8, dash: "dot", shape: sh }, xaxis: "x", yaxis: `y${ax}`, name: "scenario" });
    ann.push({ x: 0, xref: "paper", y: y0 + h / 2, yref: "paper", xanchor: "right", xshift: -6, showarrow: false, text: esc(c.name), font: { size: 11.5 } });
  });
  lay.xaxis = { gridcolor: C.grid, anchor: `y${n === 1 ? "" : n}` }; lay.annotations = ann; lay.shapes = [vline(r.dates[last], C.green)];
  const height = 40 + 60 * n; $("#wiCov").style.height = `${height}px`;
  Plotly.react("wiCov", ct, { ...lay, height }, { ...PCONF, displayModeBar: false });
}
