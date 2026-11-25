// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { band, C, label, layout, line, PCONF, unitAxis, vline } from "../core/charts.js";
import { $, esc } from "../core/dom.js";
import { chip, fmt, pct, spct } from "../core/format.js";
import { common, S } from "../core/state.js";
import { withBusy } from "../core/ui.js";

export function initPlanner() {
  $("#plRun").onclick = runPlanner;
  for (const id of ["#plTarget", "#plScope"]) $(id).onchange = runPlanner;
}
export async function runPlanner() {
  S.dirty.planner = false;
  await withBusy($("#plCard"), async () => {
    const r = await api("api/planner", common({ scope: $("#plScope").value, target: +$("#plTarget").value,
      margin: (+$("#plMargin").value || 40) / 100, holding: (+$("#plHold").value || 0) / 100 }));
    S.pl = r; renderPlanner(r);
  });
}
export const plLevel = (lv) => (lv === null || lv === undefined ? "–" : `P${Math.round(lv * 100)}`);
export const plBuffer = (k) => (k === null || k === undefined ? "–" : `${k >= 1 ? "+" : "−"}${Math.abs(Math.round((k - 1) * 100))}%`);
/** Availability vs leftover stock for both policies (also used by the chat). */
export function drawPlannerCurve(el, r, extra = {}) {
  const tc = r.timestral_curve, bc = r.baseline_curve, s = r.same;
  const tr = [
    { x: bc.map((c) => c.fill), y: bc.map((c) => c.leftover_pct), type: "scatter", mode: "lines", name: `${r.baseline} + safety buffer`,
      line: { color: "#cbd5e1", width: 2, dash: "dash" }, customdata: bc.map((c) => plBuffer(c.buffer)),
      hovertemplate: "buffer %{customdata}: availability %{x:.1%}, leftover %{y:.1%}<extra></extra>" },
    { x: tc.map((c) => c.fill), y: tc.map((c) => c.leftover_pct), type: "scatter", mode: "lines+markers", name: `${r.model.split(" · ")[0]} quantiles`,
      line: { color: C.orange, width: 2.4 }, marker: { size: 6 }, customdata: tc.map((c) => plLevel(c.level)),
      hovertemplate: "order %{customdata}: availability %{x:.1%}, leftover %{y:.1%}<extra></extra>" },
  ];
  if (s.timestral !== null && s.baseline !== null) tr.push({ x: [s.target, s.target], y: [s.timestral, s.baseline], type: "scatter", mode: "markers",
    name: `at ${pct(s.target, 0)}`, marker: { color: [C.orange, C.grey], size: 12, line: { color: "#fff", width: 1.5 } }, hoverinfo: "skip", showlegend: false });
  // zoom on the interesting part: near the target, not the extreme buffers
  const lo = Math.max(0.5, Math.min(s.target - 0.05, ...tc.map((c) => c.fill)) - 0.01);
  const ymax = 3 * Math.max(s.timestral || 0, s.baseline || 0, 0.02);
  Plotly.react(el, tr, layout({ hovermode: "closest", xaxis: { title: { text: "availability (share of demand served)", font: { size: 12, color: C.muted } }, tickformat: ".0%", range: [lo, 1.002] },
    yaxis: { title: { text: "leftover stock (% of demand)", font: { size: 12, color: C.muted } }, tickformat: ".0%", range: [0, ymax] },
    shapes: [vline(s.target, C.white, "dot")], annotations: [label(s.target, `target ${pct(s.target, 0)}`, C.white)], ...extra }), PCONF);
}
export function renderPlanner(r) {
  const s = r.same, c = r.cost, p = r.plan, u = r.meta.unit, per = r.period;
  $("#plChips").innerHTML = [chip("Model", esc(r.model)), chip("Compared with", `${esc(r.baseline)} + buffer`),
    chip("Scope", r.scope === "all" ? `all ${r.meta.n > 1 ? esc(r.meta.id_label.toLowerCase()) + "s" : "series"}` : `${esc(r.meta.id_label)} #${esc(r.id)}`),
    chip("Hidden period", `${r.windows[0].start} → ${r.windows.at(-1).end}`), chip("Scored", `${r.points.toLocaleString("en-US")} ${per}s`)].join("");
  const cards = [
    [pct(s.timestral), `leftover stock to serve ${pct(s.target, 0)} of demand`, `simple rule + buffer: ${pct(s.baseline)}`, s.saving > 0 ? "good" : "bad"],
    [s.saving === null || s.saving === undefined ? "–" : pct(s.saving, 0), "less safety stock for the same availability", `order ${plLevel(s.timestral_level)} vs rule ${plBuffer(s.baseline_buffer)}`, s.saving > 0 ? "good" : "bad"],
    [c.saving_pct === null || c.saving_pct === undefined ? "–" : pct(c.saving_pct, 0), `lower cost (lost margin + leftovers)`,
      `${fmt(c.saving)} saved on the hidden period · ≈ ${fmt(c.saving * c.per_year)}/year (rough) · unit: ${esc(u)}`, c.saving > 0 ? "good" : "bad"],
    [plLevel(c.level), "best order level for your margins", `critical ratio ${pct(c.ratio, 0)} = margin / (margin + leftover cost)`, ""],
  ];
  $("#plKpis").innerHTML = `<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(210px,1fr));margin-top:0">${cards.map(([v, l, sub, cl]) =>
    `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div><div class="s ${cl}">${sub}</div></div>`).join("")}</div>`;
  drawPlannerCurve("plCurve", r);
  // next period plan for the selected series
  $("#plSer").textContent = r.meta.n > 1 ? `${r.meta.id_label} #${p.id}` : r.meta.name;
  $("#plPlanSub").innerHTML = `Expected demand <b>${fmt(p.total_median)}</b> over the next ${p.future_dates.length} ${per}s; ordering
    <b style="color:var(--orange)">${plLevel(c.level)}</b> each ${per} means <b>${fmt(p.total_order)}</b> (${spct(p.total_median ? p.total_order / p.total_median - 1 : null, 0)} buffer, set by the model’s own uncertainty).`;
  const last = p.dates.length - 1, fx = [p.dates[last], ...p.future_dates], j = (a) => [p.y[last], ...a];
  Plotly.react("plPlan", [line(p.dates, p.y, C.white, "history", { line: { width: 1.2 } }), ...band(fx, j(p.lo), j(p.hi), C.green, "80% band", 0.18),
    line(fx, j(p.median), C.green, "expected (median)", { line: { width: 2 } }),
    line(p.future_dates, p.order, C.orange, `order ${plLevel(c.level)}`, { line: { width: 2.2, shape: "hv" } })],
  layout({ shapes: [vline(p.dates[last], C.green)], yaxis: unitAxis(u) }), PCONF);
  // cost table
  $("#plTabSub").innerHTML = `Lost margin <b>${pct(r.margin, 0)}</b> of the value of each missed sale, leftover cost <b>${pct(r.holding, 0)}</b> of the value of each unit left over
    (in ${esc(u)}). The simple rule’s buffer is the best one <i>in hindsight</i>, so the comparison favours it; Timestral uses the textbook quantile with no tuning.`;
  const best = Math.min(...r.table.map((t) => t.cost));
  $("#plTable").innerHTML = `<div class="scroll" style="max-height:none"><table><thead><tr><th>Policy</th><th title="share of demand served">Availability</th>
    <th title="share of periods with no stock-out">In-stock ${per}s</th><th>Leftover (% of demand)</th><th>Lost sales</th><th>Leftover</th><th>Total cost</th></tr></thead><tbody>${
    r.table.map((t) => `<tr class="${t.kind === "timestral" ? "t" : ""}"><td>${esc(t.name)}</td><td>${pct(t.fill)}</td><td>${pct(t.in_stock)}</td><td>${pct(t.leftover_pct)}</td>
      <td>${fmt(t.lost)}</td><td>${fmt(t.leftover)}</td><td class="${t.cost === best ? "bestcell" : ""}">${fmt(t.cost)}</td></tr>`).join("")}</tbody></table></div>`;
}
