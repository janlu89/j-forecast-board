// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { B_COLORS, band, C, label, layout, line, PCONF, unitAxis, vline, vrect } from "../core/charts.js";
import { $, $$, esc } from "../core/dom.js";
import { chip, dur, fmt, MET, mfmt, ms, pct, spct } from "../core/format.js";
import { common, ds, S } from "../core/state.js";
import { toast, withBusy } from "../core/ui.js";
import { metricTable } from "../tabs/overview.js";

export function initSplit() {
  $("#spRun").onclick = runSplit;
  $("#spBase").onchange = () => S.sp && renderSplit(S.sp);
  $$("[data-sp]").forEach((b) => (b.onclick = () => {
    const [give, fc] = b.dataset.sp.split(",").map(Number);
    const d = ds(), last = new Date(ms(d.end.slice(0, 10))), first = new Date(ms(d.start.slice(0, 10)));
    const addY = (dt, y) => new Date(dt.getTime() + y * 365.25 * 864e5);
    let start = addY(last, -(give + fc));
    if (start < first) {
      toast(`Only ${((last - first) / 365.25 / 864e5).toFixed(1)} years of data in “${d.name}”: using all of it with the same proportion.`);
      start = first;
      const tot = (last - first) / 365.25 / 864e5;
      $("#spSplit").value = iso(addY(first, tot * give / (give + fc)));
    } else $("#spSplit").value = iso(addY(start, give));
    $("#spStart").value = iso(start); $("#spEnd").value = iso(last);
    runSplit();
  }));
}
export const iso = (d) => d.toISOString().slice(0, 10);
export async function runSplit() {
  S.dirty.split = false;
  await withBusy($("#spCard"), async () => {
    const r = await api("api/split", common({ start: $("#spStart").value || null, split: $("#spSplit").value || null, end: $("#spEnd").value || null }));
    S.sp = r;
    $("#spStart").value = r.start.slice(0, 10); $("#spSplit").value = r.split.slice(0, 10); $("#spEnd").value = r.end.slice(0, 10);
    for (const id of ["#spStart", "#spSplit", "#spEnd"]) { $(id).min = r.first.slice(0, 10); $(id).max = r.last.slice(0, 10); }
    $("#spPlot .empty")?.remove();
    renderSplit(r);
  });
}
export function renderSplit(r) {
  const c = r.cut, f = r.forecast, P = r.primary, h = r.how;
  const split = r.dates[c - 1], fx = [split, ...r.dates.slice(c)], j = (a) => [r.y[c - 1], ...a];
  const tr = [line(r.dates.slice(0, c), r.y.slice(0, c), C.white, "data given to the model", { line: { width: 1.1 } }),
    line(r.dates.slice(c - 1), r.y.slice(c - 1), "#7c8396", "what really happened (hidden)", { line: { width: 1 } }),
    ...band(fx, j(f.lo90), j(f.hi90), C.green, "90% band", 0.1), ...band(fx, j(f.lo), j(f.hi), C.green, "80% band", 0.22),
    line(fx, j(f.median), C.green, `${r.model.split(" · ")[0]} forecast`, { line: { width: 1.8 } })];
  if ($("#spBase").checked) tr.push(line(r.dates.slice(c), r.baselines[r.best_baseline], C.yellow, `${r.best_baseline} (best simple rule)`, { line: { width: 1.1, dash: "dot" } }));
  Plotly.react("spPlot", tr, layout({ shapes: [vrect(split, r.dates.at(-1), C.green, 0.04), vline(split, C.white)],
    annotations: [label(r.dates[0], "seen by the model", C.white), label(split, "hidden from the model → forecast", C.green)],
    yaxis: unitAxis(r.meta.unit), margin: { l: 64, r: 18, t: 44, b: 10 },
    xaxis: { rangeslider: { visible: true, thickness: 0.07, bgcolor: "#0b0d12", bordercolor: "#232838", borderwidth: 1 } } }), PCONF);
  const t = r.leaderboard.find((x) => x.kind === "timestral"), b = r.leaderboard.find((x) => x.kind === "baseline");
  const win = t[P] <= b[P];
  $("#spChips").innerHTML = [chip(r.meta.n > 1 ? r.meta.id_label : "Series", `#${esc(r.id)}`), chip("Given", `${r.start} → ${r.split} (${fmt(h.years_seen, 1)} y)`),
    chip("Forecast", `${fmt(h.years_forecast, 1)} y · ${h.horizon.toLocaleString("en-US")} steps`), chip(`Timestral ${MET[P][0]}`, mfmt(P, t[P]), win ? "good" : "bad"),
    chip(`${esc(b.name)}`, mfmt(P, b[P])), chip("Cov. 80%", pct(t.coverage, 0)), chip("Bias", spct(t.bias)), chip("Compute", dur(r.seconds))].join("");
  // error by period
  const names = ["Timestral", ...Object.keys(r.baselines)];
  const cols = { Timestral: C.orange };
  Object.keys(r.baselines).forEach((n, i) => (cols[n] = B_COLORS[i % B_COLORS.length]));
  Plotly.react("spPer", names.map((n) => ({ x: r.periods.map((p) => p.label), y: r.periods.map((p) => p[n]), type: "bar", name: n, marker: { color: cols[n] },
    hovertemplate: `%{y${P === "mase" ? ":.3f" : ":.2%"}}` })), layout({ barmode: "group", hovermode: "x", xaxis: { type: "category" },
    yaxis: P === "mase" ? { title: { text: "MASE", font: { size: 11 } } } : { tickformat: ".0%", title: { text: MET[P][0], font: { size: 11 } } }, legend: { font: { size: 10.5 } } }), PCONF);
  // how
  const per = r.periods.filter((p) => p.Timestral !== null);
  const firstP = per[0], lastP = per.at(-1);
  $("#spHow").innerHTML = `<ul>
    <li><b>What it saw:</b> ${fmt(h.years_seen, 1)} years (${h.context.toLocaleString("en-US")} points, ${fmt(h.cycles, 0)} cycles of ${h.season}). Nothing after ${r.split}.</li>
    <li><b>What it had to do:</b> forecast ${fmt(h.years_forecast, 1)} years (${h.horizon.toLocaleString("en-US")} points) – ${fmt(h.ratio, 1)}× the length it saw. No training: zero-shot, from the shape of the history${h.known.length ? ` plus <b>${h.known.map(esc).join(", ")}</b> known over the whole forecast (taken from the real data, as if planned)` : ""}.</li>
    <li><b>How:</b> for every step it outputs ${h.quantiles} quantiles (a full distribution, not one number).${h.block ? ` Long horizons are produced in blocks of ${h.block} steps (${h.blocks} block${h.blocks > 1 ? "s" : ""}): each block is fed back as if it were data, so small errors can accumulate.` : ""}</li>
    <li><b>Uncertainty:</b> the 80% band is about ±${pct(h.width_first / 2, 0)} of the level at the start and ±${pct(h.width_last / 2, 0)} at the end${h.width_last > h.width_first * 1.2 ? " – it knows it is less sure far ahead" : ""}.</li>
    ${firstP && lastP && per.length > 1 ? `<li><b>Over time:</b> ${MET[P][0]} goes from ${mfmt(P, firstP.Timestral)} in ${firstP.label} to ${mfmt(P, lastP.Timestral)} in ${lastP.label}.</li>` : ""}
    <li><b>Verdict:</b> ${win ? `<span style="color:var(--green)">Timestral beats every simple rule</span> on the hidden period (${mfmt(P, t[P])} vs ${mfmt(P, b[P])} for “${esc(b.name)}”).`
      : `<span style="color:var(--red)">“${esc(b.name)}” is better here</span> (${mfmt(P, b[P])} vs ${mfmt(P, t[P])}): very regular series repeat themselves and a simple rule is hard to beat far ahead.`}</li></ul>`;
  $("#spLb").innerHTML = metricTable(r.leaderboard, ["mape", "wape", "mase", "bias", "mae", "rmse", "coverage", "width"].filter((k) => P === "mape" || k !== "mape"), { first: true });
  const word = r.agg === "sum" ? "totals" : "averages";
  $("#spTabSub").textContent = `${r.table.length > 0 && r.table[0].period.length > 4 ? "Monthly" : "Yearly"} ${word}: real vs Timestral vs “${r.best_baseline}”. Error = forecast − actual.`;
  const ec = (v) => (v === null ? "" : Math.abs(v) < 0.05 ? "color:var(--green)" : Math.abs(v) > 0.15 ? "color:var(--red)" : "");
  $("#spTable").innerHTML = `<table><thead><tr><th>Period</th><th>Actual</th><th>Timestral</th><th>80% range</th><th>Error</th><th>${esc(r.best_baseline)}</th><th>Error</th></tr></thead><tbody>${
    r.table.map((x) => `<tr><td>${x.period}</td><td>${fmt(x.actual)}</td><td>${fmt(x.forecast)}</td><td>${fmt(x.lo)} … ${fmt(x.hi)}</td><td style="${ec(x.err)}">${spct(x.err)}</td><td>${fmt(x.baseline)}</td><td style="${ec(x.base_err)}">${spct(x.base_err)}</td></tr>`).join("")}</tbody></table>`;
}
