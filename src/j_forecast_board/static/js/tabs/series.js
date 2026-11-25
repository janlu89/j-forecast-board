// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { band, C, label, layout, line, PCONF, rgba, unitAxis, vline, vrect } from "../core/charts.js";
import { $, $$, esc } from "../core/dom.js";
import { chip, csvCell, MET, mfmt, ms, pct } from "../core/format.js";
import { common, S, variant } from "../core/state.js";
import { withBusy } from "../core/ui.js";
import { metricTable } from "../tabs/overview.js";

export function initSeries() {
  $$("#tab-series [data-view]").forEach((b) => (b.onclick = () => {
    $$("#tab-series [data-view]").forEach((x) => x.classList.toggle("active", x === b)); S.view = b.dataset.view; applyView();
  }));
  S.view = "recent";
  $("#seBaseline").onchange = () => S.se && Plotly.restyle("sePlot", { visible: $("#seBaseline").checked }, S.seBaseIdx);
  $("#seCsv").onclick = () => {
    const r = S.se; if (!r?.future) return;
    const f = r.future;
    const rows = ["date,forecast,p10,p90,p5,p95", ...r.future_dates.map((d, i) => [d, f.median[i], f.lo[i], f.hi[i], f.lo90[i], f.hi90[i]].map(csvCell).join(","))];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv" }));
    a.download = `forecast_${r.meta.key}_${r.id}.csv`; a.click();
  };
}
export async function runSeries() {
  await withBusy($("#seCard"), async () => { S.se = await api("api/series", common()); renderSeries(S.se); });
}
export function renderSeries(r) {
  const T = r.dates.length, H = r.H, last = r.dates[T - 1], fd = r.future_dates;
  const tr = [line(r.dates, r.y, C.white, "actual", { line: { width: 1.1 } })];
  const shapes = [], ann = [];
  S.seBaseIdx = [];
  r.cuts.forEach((c, w) => {
    const x = r.dates.slice(c, c + H);
    if (r.holdout) {
      tr.push(...band(x, r.holdout[w].lo, r.holdout[w].hi, C.orange, "holdout 80%", 0.25, w === 0));
      tr.push(line(x, r.holdout[w].median, C.orange, `${r.model.split(" · ")[0]} (holdout)`, { line: { width: 2 }, showlegend: w === 0 }));
    }
    S.seBaseIdx.push(tr.length);
    tr.push(line(x, r.baseline.values[w], C.grey, `baseline: ${r.baseline.name}`, { line: { dash: "dot", width: 1.3 }, visible: $("#seBaseline").checked, showlegend: w === 0 }));
    shapes.push(vline(r.dates[c], C.orange));
  });
  const c0 = r.dates[r.cuts[0]];
  shapes.unshift(vrect(c0, last, C.orange, 0.07));
  ann.push(label(c0, "holdout start (hidden from the model)", C.orange));
  if (r.future) {
    const fx = [last, ...fd], j = (a) => [r.y[T - 1], ...a];
    tr.push(...band(fx, j(r.future.lo90), j(r.future.hi90), C.green, "future 90%", 0.12));
    tr.push(...band(fx, j(r.future.lo), j(r.future.hi), C.green, "future 80%", 0.25));
    tr.push(line(fx, j(r.future.median), C.green, `${r.model.split(" · ")[0]} (future)`, { line: { width: 2 } }));
    S.seSeries = [[fx.map(ms), j(r.future.lo90)], [fx.map(ms), j(r.future.hi90)]];
  } else S.seSeries = [];
  shapes.push(vrect(last, fd.at(-1), C.green, 0.05), vline(last, C.green));
  ann.push(label(last, "future", C.green));
  Plotly.react("sePlot", tr, layout({ shapes, annotations: ann, margin: { l: r.covariates.length ? 130 : 64, r: 18, t: 44, b: 10 }, yaxis: unitAxis(r.meta.unit),
    xaxis: { rangeslider: { visible: true, thickness: 0.08, bgcolor: "#0b0d12", bordercolor: "#232838", borderwidth: 1 } } }), PCONF);
  S.seSeries.push([r.dates.map(ms), r.y]);
  r.cuts.forEach((c, w) => { if (r.holdout) { const xm = r.dates.slice(c, c + H).map(ms); S.seSeries.push([xm, r.holdout[w].lo], [xm, r.holdout[w].hi]); } });
  S.seBounds = { first: r.dates[0], last: fd.at(-1), recent: r.dates[Math.max(0, r.cuts[0] - Math.max(2 * H, 4 * r.meta.season))] };
  const el = $("#sePlot"); el.removeAllListeners?.("plotly_relayout"); el.on("plotly_relayout", onSeRelayout);
  // chips
  const P = r.primary, mine = r.table.find((t) => t.key === r.variant);
  const attrs = Object.entries(r.attrs).map(([k, v]) => chip(esc(k), esc(typeof v === "number" ? v.toLocaleString("en-US") : v))).join("");
  $("#seChips").innerHTML = (r.meta.n > 1 ? chip(esc(r.meta.id_label), `#${esc(r.id)}`) : chip("Series", esc(r.id))) + attrs +
    (mine ? chip(`${MET[P][0]} backtest`, mfmt(P, mine[P]), "good") + chip("Cov. 80%", pct(mine.coverage, 0)) : "") + chip("Model", esc(r.model));
  $("#seTable").innerHTML = metricTable(r.table, ["mape", "rmspe", "wape", "mase", "bias", "mae", "coverage"].filter((k) => P === "mape" || !["mape", "rmspe"].includes(k)), { first: true });
  renderCovariates(r);
  applyView();
}
export function onSeRelayout(ev) {
  if (S.seSync) return;
  let rg = ev["xaxis.range"] || (ev["xaxis.range[0]"] !== undefined ? [ev["xaxis.range[0]"], ev["xaxis.range[1]"]] : null);
  if (ev["xaxis.autorange"]) rg = [S.seBounds.first, S.seBounds.last];
  if (rg) setSeRange(rg);
}
export function applyView() {
  if (!S.seBounds) return;
  const b = S.seBounds;
  const start = S.view === "all" ? b.first : S.view === "year"
    ? new Date(Math.max(ms(b.first), ms(b.last) - 365 * 864e5)).toISOString().slice(0, 16).replace("T", " ") : b.recent;
  setSeRange([start, b.last]);
}
export function setSeRange(rg) {
  const x0 = ms(rg[0]), x1 = ms(rg[1]);
  let lo = Infinity, hi = -Infinity;
  for (const [xs, ys] of S.seSeries) for (let i = 0; i < xs.length; i++) {
    if (xs[i] < x0 || xs[i] > x1) continue;
    const v = ys[i]; if (v === null) continue; if (v < lo) lo = v; if (v > hi) hi = v;
  }
  const upd = { "xaxis.range": rg };
  if (lo < hi) { const p = (hi - lo) * 0.07; upd["yaxis.range"] = [lo - p, hi + p]; }
  S.seSync = true;
  Plotly.relayout("sePlot", upd).finally(() => { S.seSync = false; });
  if (S.covOn) Plotly.relayout("covPlot", { "xaxis.range": rg });
}
export function renderCovariates(r) {
  const covs = r.covariates;
  S.covOn = covs.length > 0;
  $("#covCard").style.display = covs.length ? "" : "none";
  if (!covs.length) { Plotly.purge("covPlot"); return; }
  const kinds = new Set(covs.map((c) => c.kind));
  $("#covSub").innerHTML = (kinds.has("known") ? "<b>Known in advance</b> – also over the future (faded = estimated). " : "") + (kinds.has("past") ? "<b>Past-only</b> covariates – known up to today. " : "") +
    (variant().includes("|nocov|") ? "<span style='color:#fbbf24'>The selected model variant does NOT use them.</span>" : "");
  const n = covs.length, gap = 0.04, h = (1 - gap * (n - 1)) / n;
  const traces = [], lay = layout({ margin: { l: 64, r: 18, t: 8, b: 30 }, showlegend: false, hovermode: "x unified" });
  const last = r.dates.at(-1), c0 = r.dates[r.cuts[0]], ann = [];
  covs.forEach((c, i) => {
    const ax = i === 0 ? "" : String(i + 1), y0 = 1 - (i + 1) * h - i * gap;
    lay[`yaxis${ax}`] = { domain: [y0, y0 + h], gridcolor: C.grid, zeroline: false, fixedrange: true, showticklabels: !c.cat, nticks: 3, tickfont: { size: 10 } };
    const binary = c.cat && c.values.every((v) => v === null || v === 0 || v === 1);
    const mk = (x, y, op, name) => binary
      ? { x, y, type: "bar", marker: { color: rgba(C.blue, op) }, xaxis: "x", yaxis: `y${ax}`, name, hovertemplate: "%{y}" }
      : { x, y, type: "scatter", mode: "lines", line: { color: rgba(C.blue, op), width: 1.3, shape: c.cat ? "hv" : "linear" }, xaxis: "x", yaxis: `y${ax}`, name, hovertemplate: "%{y:,.2f}" };
    traces.push(mk(r.dates, c.values, 1, c.name));
    if (c.future) {
      traces.push(mk(r.future_dates, c.future.map((v, k) => (c.assumed[k] ? null : v)), 1, c.name));
      if (c.assumed.some((x) => x)) traces.push(mk(r.future_dates, c.future.map((v, k) => (c.assumed[k] ? v : null)), 0.4, `${c.name} (estimated)`));
    }
    ann.push({ x: 0, xref: "paper", y: y0 + h / 2, yref: "paper", xanchor: "right", yanchor: "middle", xshift: -6, showarrow: false, text: esc(c.name), font: { size: 11.5, color: C.white } });
  });
  lay.margin.l = 130;
  lay.xaxis = { gridcolor: C.grid, linecolor: C.line, anchor: `y${n === 1 ? "" : n}` };
  lay.bargap = 0.12; lay.annotations = ann;
  lay.shapes = [vrect(c0, last, C.orange, 0.06), vline(c0, C.orange), vrect(last, r.future_dates.at(-1), C.green, 0.05), vline(last, C.green)];
  const height = 40 + 46 * n + (n < 3 ? 40 : 0);
  $("#covPlot").style.height = `${height}px`;
  Plotly.react("covPlot", traces, { ...lay, height }, { ...PCONF, displayModeBar: false });
}
