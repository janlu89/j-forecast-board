// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { C, label, layout, line, PCONF, unitAxis, vline, vrect } from "../core/charts.js";
import { $, esc } from "../core/dom.js";
import { chip, dur, MET, mfmt, ms, pct, spct } from "../core/format.js";
import { common, ds, S } from "../core/state.js";
import { withBusy } from "../core/ui.js";

export function initLive() {
  $("#lvRun").onclick = runLive;
  $("#lvEnd").onclick = () => { $("#lvDate").value = ""; runLive(); };
  $("#lvBack").onclick = () => {
    const cur = $("#lvDate").value || S.lv?.last?.slice(0, 10); if (!cur) return;
    const d = new Date(ms(cur) - (+$("#horizon").value || ds().horizon) * stepMs()); $("#lvDate").value = d.toISOString().slice(0, 10); runLive();
  };
  $("#lvRand").onclick = () => {
    if (!S.lv) return;
    const a = ms(S.lv.first), b = ms(S.lv.last); $("#lvDate").value = new Date(a + Math.random() * (b - a)).toISOString().slice(0, 10); runLive();
  };
}
export const stepMs = () => ({ h: 3600e3, D: 864e5, "7D": 7 * 864e5, MS: 30.4 * 864e5 }[ds().freq] || 864e5);
export async function runLive() {
  S.dirty.live = false;
  await withBusy($("#lvCard"), async () => {
    const r = await api("api/live", common({ origin: $("#lvDate").value || null }));
    S.lv = r;
    $("#lvPlot .empty")?.remove();
    renderLive(r);
  });
}
/** Forecast chart of an api/live result (also used by the chat). Returns the forecast origin date. */
export function drawLive(el, r, extra = {}) {
  const c = r.cut_offset, f = r.forecast, today = r.dates[c - 1];
  const fx = [today, ...r.fdates], j = (a) => [r.y[c - 1], ...a];
  const tr = [line(r.dates.slice(0, c), r.y.slice(0, c), C.white, "history", { line: { width: 1.2 } })];
  if (r.dates.length > c) tr.push(line(r.dates.slice(c - 1), r.y.slice(c - 1), "#8a90a2", "what really happened", { line: { width: 1.4, dash: "dot" } }));
  tr.push(...band(fx, j(f.lo90), j(f.hi90), C.green, "90% band", 0.12), ...band(fx, j(f.lo), j(f.hi), C.green, "80% band", 0.25),
    line(fx, j(f.median), C.green, "forecast", { line: { width: 2.2 } }));
  Plotly.react(el, tr, layout({ shapes: [vline(today, C.white), vrect(today, r.fdates.at(-1), C.green, 0.05)], annotations: [label(today, `forecast from ${today}`, C.white)],
    yaxis: unitAxis(r.meta.unit), ...extra }), PCONF);
  return today;
}
export function renderLive(r) {
  $("#lvDate").min = r.first.slice(0, 10); $("#lvDate").max = r.last.slice(0, 10);
  if (!$("#lvDate").value) $("#lvDate").placeholder = r.last.slice(0, 10);
  const today = drawLive("lvPlot", r);
  const m = r.metrics, P = r.meta.primary;
  $("#lvChips").innerHTML = [chip(r.meta.n > 1 ? r.meta.id_label : "Series", `#${esc(r.id)}`), chip("From", today), chip("Horizon", `${r.horizon} steps`), chip("Model", esc(r.model)),
    m && m[P] !== undefined ? chip(`${MET[P][0]} vs reality`, mfmt(P, m[P]), "good") + chip("Cov. 80%", pct(m.coverage, 0)) + chip("Bias", spct(m.bias)) : chip("Reality", "not known yet – true forecast"),
    chip("Compute", dur(r.seconds))].join("");
}
