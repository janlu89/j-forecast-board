// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { band, C, label, layout, line, PCONF, unitAxis, vline } from "../core/charts.js";
import { $, esc } from "../core/dom.js";
import { chip, dur, fmt, pct } from "../core/format.js";
import { common, S } from "../core/state.js";
import { withBusy } from "../core/ui.js";

export function initAnomalies() { $("#adRun").onclick = runAnomalies; }
export async function runAnomalies() {
  S.dirty.anomalies = false;
  await withBusy($("#adCard"), async () => {
    const r = await api("api/anomalies", common({ step: +$("#adStep").value || null, windows: +$("#adWin").value, level: +$("#adLevel").value }));
    S.ad = r; renderAnomalies(r);
  });
}
export function renderAnomalies(r) {
  const o = r.offset, x = r.dates.slice(o), act = r.y.slice(o);
  const sev = new Map(r.anomalies.map((a) => [a.date, a.score]));
  const fx = r.flags.map((i) => x[i]), fy = r.flags.map((i) => act[i]), lvl = pct(r.level, 0);
  $("#adPlot").innerHTML = "";
  Plotly.react("adPlot", [line(r.dates, r.y, C.white, "actual", { line: { width: 1.2 } }), ...band(x, r.lo, r.hi, C.blue, `expected ${lvl} band`, 0.18),
    line(x, r.median, C.blue, "expected (median)", { line: { width: 1.2, dash: "dot" } }),
    { x: fx, y: fy, mode: "markers", name: "anomaly", type: "scatter", hovertemplate: "%{y:,.2f} ⚠<extra></extra>",
      marker: { color: C.red, size: fx.map((d) => 8 + Math.min(12, Math.abs(sev.get(d) || 0) * 5)), line: { color: "#fff", width: 1 } } }],
  layout({ shapes: [vline(x[0], C.blue)], annotations: [label(x[0], `scanned: last ${act.length} points`, C.blue)], yaxis: unitAxis(r.meta.unit) }), PCONF);
  $("#adChips").innerHTML = [chip(r.meta.n > 1 ? r.meta.id_label : "Series", `#${esc(r.id)}`), chip("Anomalies", r.anomalies.length, r.anomalies.length ? "bad" : "good"),
    chip("Outside band", pct(r.rate, 1), r.rate > 2 * r.expected_rate ? "bad" : "good"), chip("Expected by chance", pct(r.expected_rate, 0)),
    chip("Windows", `${r.windows} × ${r.step} steps`), chip("Model", esc(r.model)), chip("Compute", dur(r.seconds))].join("");
  $("#adTable").innerHTML = r.anomalies.length ? `<table><thead><tr><th>Date</th><th>Actual</th><th>Expected</th><th>${lvl} band</th><th>Direction</th><th>Severity</th></tr></thead><tbody>${
    r.anomalies.slice(0, 200).map((a) => `<tr><td>${a.date}</td><td>${fmt(a.actual)}</td><td>${fmt(a.expected)}</td><td>${fmt(a.lo)} … ${fmt(a.hi)}</td>
      <td style="color:${a.direction === "above" ? C.orange : C.blue}">${a.direction === "above" ? "▲ above" : "▼ below"}</td><td>${fmt(Math.abs(a.score), 2)}× band</td></tr>`).join("")}</tbody></table>`
    : `<div class="empty">No points outside the ${lvl} band.</div>`;
}
