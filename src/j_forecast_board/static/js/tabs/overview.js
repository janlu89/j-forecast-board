// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { B_COLORS, C, layout, line, PCONF, T_COLORS } from "../core/charts.js";
import { $, $$, esc } from "../core/dom.js";
import { dur, MET, mfmt, pct, spct } from "../core/format.js";
import { common, ds, S } from "../core/state.js";
import { withBusy } from "../core/ui.js";
import { refreshStatus, setSeries, showTab } from "../main.js";

export async function runOverview() {
  await withBusy($("#ovOut"), async () => { S.ov = await api("api/overview", common()); renderOverview(S.ov); });
}
export function bestCols(rows, keys) {
  const best = {};
  for (const k of keys) {
    const vals = rows.map((r) => r[k]).filter((v) => v !== null && v !== undefined);
    if (!vals.length) continue;
    best[k] = k === "bias" ? vals.reduce((a, b) => (Math.abs(b) < Math.abs(a) ? b : a))
      : k === "coverage" ? vals.reduce((a, b) => (Math.abs(b - 0.8) < Math.abs(a - 0.8) ? b : a)) : Math.min(...vals);
  }
  return best;
}
export function metricTable(rows, keys, opts = {}) {
  const best = bestCols(rows, keys.filter((k) => k !== "secs"));
  return `<div class="scroll" style="max-height:none"><table><thead><tr><th>Model</th>${keys.map((k) => `<th title="${MET[k]?.[2] || ""}">${MET[k]?.[0] || k}</th>`).join("")}</tr></thead><tbody>${
    rows.map((r, i) => `<tr class="${r.kind === "timestral" ? "t" : ""} ${i === 0 && opts.first ? "best" : ""}"><td>${esc(r.name)}${i === 0 && opts.first ? " 🏆" : ""}</td>${
      keys.map((k) => `<td class="${best[k] !== undefined && r[k] === best[k] ? "bestcell" : ""}">${r[k] === null || r[k] === undefined ? "–" : mfmt(k, r[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
export function renderOverview(o) {
  const d = o.meta, P = o.primary, k = o.kpi;
  const ho = o.holdout, nH = o.H;
  const summary = `History <b>${d.start} → ${d.end}</b> (${d.n.toLocaleString("en-US")} ${d.n > 1 ? esc(d.id_label.toLowerCase()) + "s" : "series"}, ${d.points.toLocaleString("en-US")} ${d.freq === "h" ? "hours" : d.freq === "D" ? "days" : "points"}).
    <b>Holdout${ho.length > 1 ? ` (${ho.length} windows)` : ""}:</b> ${ho.length > 1 ? `${ho[0].start} → ${ho.at(-1).end}` : `${ho[0].start} → ${ho[0].end}`} (${nH} steps each), never seen by the model.
    <b>Future forecast:</b> ${o.future.start} → ${o.future.end}. Best model: <b style="color:var(--orange)">${esc(o.best || "–")}</b>.
    Scored on <b>${o.scored_points.toLocaleString("en-US")}</b> points.`;
  let kpis = "";
  if (k) {
    const m = k.model, b = k.baseline, g = k.gain;
    const covCls = m.coverage === null ? "" : m.coverage < 0.72 ? "warn" : m.coverage > 0.88 ? "warn" : "good";
    const covTxt = m.coverage === null ? "" : m.coverage < 0.72 ? "too narrow (over-confident)" : m.coverage > 0.88 ? "too wide (cautious)" : "well calibrated";
    const card = (key, lab) => [mfmt(key, m[key]), lab, `baseline: ${mfmt(key, b[key])}`, m[key] !== null && b[key] !== null && Math.abs(m[key]) < Math.abs(b[key]) ? "good" : ""];
    const second = { mape: [card("rmspe", "RMSPE · Kaggle metric"), card("wape", "WAPE · weighted by volume")],
      wape: [card("mase", "MASE · below 1 = beats naive"), card("smape", "sMAPE · symmetric % error")],
      mase: [card("wape", "WAPE · weighted by volume"), card("mae", `MAE · in ${d.unit}`)] }[P];
    const cards = [
      [mfmt(P, m[P]), `${MET[P][0]} · ${P === "mape" ? `daily error per ${d.n > 1 ? d.id_label.toLowerCase() : "point"}` : MET[P][2]}`,
        g === null ? "" : `${pct(Math.abs(g), 0)} ${g >= 0 ? "better" : "worse"} than “${esc(b.name)}” (${mfmt(P, b[P])})`, g >= 0 ? "good" : "bad"],
      ...second,
      [pct(m.coverage, 1), "Coverage of the 80% band", covTxt, covCls],
      o.total_kpi !== undefined && o.total_kpi !== null ? [pct(o.total_kpi, 2), "MAPE on the total", `sum of all ${esc(d.id_label.toLowerCase())}s`, ""]
        : [spct(m.bias, 1), "Bias", m.bias > 0.02 ? "over-forecasts" : m.bias < -0.02 ? "under-forecasts" : "no systematic bias", Math.abs(m.bias) > 0.05 ? "warn" : "good"],
      [dur(k.secs_total), "Compute time (CPU)", `${d.n.toLocaleString("en-US")} series × ${o.windows > 1 ? `${o.windows} windows × ` : ""}${nH} steps + future`, ""],
    ];
    kpis = `<div class="kpis">${cards.map(([v, l, s, c]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div><div class="s ${c}">${s}</div></div>`).join("")}</div>`;
  }
  const keys = ["mape", "rmspe", "wape", "smape", "mase", "bias", "mae", "rmse", "wql", "coverage", "width", "secs"]
    .filter((x) => P === "mape" || !["mape", "rmspe"].includes(x));
  const lb = metricTable(o.leaderboard, keys, { first: true });
  const notes = d.notes?.length ? `<ul class="notes">${d.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : "";
  const panelCharts = d.n > 1 && !o.per_window;
  $("#ovOut").classList.remove("card");
  $("#ovOut").innerHTML = `
    <div class="card"><p class="summary">${summary}</p>${notes}${kpis}</div>
    <div class="card"><h3>Leaderboard on the holdout</h3><div class="sub">Ranked by ${MET[P][0]}. Green = best value in each column. ${d.n > 1 && d.key === "rossmann" ? "Only days with sales are scored, as in the Kaggle competition." : ""}</div>
      ${lb}<div class="runbar"></div></div>
    <div class="grid3">
      <div class="card"><h3>Error by forecast step</h3><div class="sub">${MET[P][0]} at 1, 2, … ${nH} steps ahead: how fast accuracy degrades.</div><div id="ovStep" class="plot" style="height:300px"></div></div>
      ${panelCharts ? `<div class="card"><h3>Error distribution per ${esc(d.id_label.toLowerCase())}</h3><div class="sub">${MET[P][0]} of each ${esc(d.id_label.toLowerCase())}: further left is better.</div><div id="ovDist" class="plot" style="height:300px"></div></div>`
        : `<div class="card"><h3>Error by backtest window</h3><div class="sub">Stability across ${o.windows} different periods.</div><div id="ovWin" class="plot" style="height:300px"></div></div>`}
      <div class="card"><h3>Error by ${esc(o.calendar.name)}</h3><div class="sub">Where in the cycle the model struggles (best Timestral vs best baseline).</div><div id="ovCal" class="plot" style="height:300px"></div></div>
      <div class="card"><h3>Calibration</h3><div class="sub">Share of real values inside each uncertainty band. On the diagonal = honest uncertainty.</div><div id="ovCalib" class="plot" style="height:300px"></div></div>
      ${d.n > 1 && Object.keys(o.breakdown || {}).length ? `<div class="card"><div class="hdr"><h3>WAPE by ${esc(d.id_label.toLowerCase())} group</h3><select id="ovAttr">${Object.keys(o.breakdown).map((a) => `<option>${esc(a)}</option>`).join("")}</select></div><div class="sub">Are some groups harder to forecast?</div><div id="ovBreak" class="plot" style="height:300px"></div></div>` : ""}
      ${d.n > 1 ? `<div class="card"><h3>Best and worst ${esc(d.id_label.toLowerCase())}s</h3><div class="sub">${MET[P][0]} of ${esc(o.best)} vs the best baseline. Click a row to open it.</div><div class="grid3" style="gap:10px">${bwTable(o.best_series, "Best", P)}${bwTable(o.worst_series, "Worst", P)}</div></div>` : ""}
    </div>`;
  renderRunbar();
  const rowsByName = Object.fromEntries(o.leaderboard.map((r) => [r.name, r]));
  const tIdx = {}, bIdx = {};
  o.leaderboard.forEach((r) => { if (r.kind === "timestral") tIdx[r.name] = Object.keys(tIdx).length; else bIdx[r.name] = Object.keys(bIdx).length; });
  const col = (n) => (rowsByName[n]?.kind === "timestral" ? T_COLORS[tIdx[n] % T_COLORS.length] : B_COLORS[(bIdx[n] ?? 0) % B_COLORS.length]);
  const isT = (n) => rowsByName[n]?.kind === "timestral";
  const pctAxis = P === "mase" ? {} : { tickformat: ".0%" };
  const steps = [...Array(nH).keys()].map((i) => i + 1);
  Plotly.react("ovStep", Object.entries(o.by_step).map(([n, v]) => line(steps, v, col(n), n, {
    line: { width: isT(n) ? 2.2 : 1.2, dash: isT(n) ? "solid" : "dot" }, hovertemplate: P === "mase" ? "%{y:.3f}" : "%{y:.2%}" })),
  layout({ hovermode: "x", yaxis: pctAxis, xaxis: { title: { text: "steps ahead", font: { size: 11 } } }, legend: { font: { size: 10.5 } } }), PCONF);
  if (panelCharts) {
    Plotly.react("ovDist", Object.entries(o.distribution).map(([n, v]) => ({ x: v, type: "histogram", name: n, opacity: 0.65, marker: { color: col(n) }, nbinsx: 50 })),
      layout({ barmode: "overlay", hovermode: "closest", xaxis: { ...pctAxis, title: { text: MET[P][0], font: { size: 11 } } }, yaxis: { title: { text: `${d.id_label.toLowerCase()}s`, font: { size: 11 } } } }), PCONF);
  } else if (o.per_window) {
    Plotly.react("ovWin", Object.entries(o.per_window.values).map(([n, v]) => ({ x: o.per_window.labels, y: v, type: "bar", name: n, marker: { color: col(n) } })),
      layout({ barmode: "group", hovermode: "x", yaxis: pctAxis, xaxis: { type: "category" }, legend: { font: { size: 10.5 } } }), PCONF);
  }
  Plotly.react("ovCal", Object.entries(o.calendar.values).map(([n, v]) => ({ x: o.calendar.labels, y: v, type: "bar", name: n, marker: { color: col(n) } })),
    layout({ barmode: "group", hovermode: "x", yaxis: pctAxis, xaxis: { type: "category" } }), PCONF);
  const ct = [{ x: [0, 1], y: [0, 1], mode: "lines", line: { color: C.grey, dash: "dot", width: 1 }, name: "ideal", hoverinfo: "skip" }];
  Object.entries(o.calibration).forEach(([n, pts]) => ct.push({ x: pts.map((p) => p.nominal), y: pts.map((p) => p.observed), mode: "lines+markers", name: n,
    line: { color: col(n), width: 2 }, marker: { size: 7 }, hovertemplate: "band %{x:.0%} → %{y:.1%} inside<extra></extra>" }));
  Plotly.react("ovCalib", ct, layout({ hovermode: "closest", xaxis: { range: [0, 1.02], tickformat: ".0%", title: { text: "nominal band", font: { size: 11 } } },
    yaxis: { range: [0, 1.02], tickformat: ".0%", title: { text: "observed inside", font: { size: 11 } } }, legend: { font: { size: 10.5 } } }), PCONF);
  if ($("#ovAttr")) {
    const draw = () => { const b = o.breakdown[$("#ovAttr").value];
      Plotly.react("ovBreak", Object.entries(b.values).map(([n, v]) => ({ x: b.labels, y: v, type: "bar", name: n, marker: { color: col(n) } })),
        layout({ barmode: "group", hovermode: "x", yaxis: { tickformat: ".0%" }, xaxis: { type: "category" }, legend: { font: { size: 10.5 } } }), PCONF); };
    $("#ovAttr").onchange = draw; draw();
  }
  $$("#ovOut tr[data-i]").forEach((tr) => (tr.onclick = () => { setSeries(+tr.dataset.i); showTab("series"); }));
}
export function bwTable(rows, title, P) {
  return `<div><div class="note" style="margin-bottom:4px">${title}</div><table><thead><tr><th>${esc(ds().id_label)}</th><th>Timestral</th><th>Baseline</th></tr></thead><tbody>${
    rows.map((r) => `<tr class="click" data-i="${r.index}"><td>#${esc(r.id)}</td><td>${mfmt(P, r.model)}</td><td>${mfmt(P, r.baseline)}</td></tr>`).join("")}</tbody></table></div>`;
}
export function renderRunbar() {
  const bar = $("#ovOut .runbar"); if (!bar || !S.status) return;
  // offer each model in its main configuration (covariates on, closures missing) plus anything already running
  const notDone = S.status.variants.filter((v) => !v.done && (v.state === "running" || v.state === "queued"
    || (!v.key.includes("|nocov|") && !v.key.includes("|zero"))));
  if (!notDone.length) { bar.innerHTML = ""; return; }
  const n = ds().n;
  bar.innerHTML = `<span class="note">Add to the comparison:</span>` + notDone.map((v) => v.state === "running" || v.state === "queued"
    ? `<span class="chip">${esc(v.label)} ${v.state === "running" ? `<span class="prog"><i style="width:${(v.progress || 0) * 100}%"></i></span> ${pct(v.progress, 0)}${v.eta ? ` · ~${dur(v.eta)}` : ""}` : "<b>queued</b>"}</span>`
    : `<button data-v="${v.key}" title="${n > 100 && v.model === "Timestral-209M" ? "about 8× slower than 28M on CPU" : ""}">▶ ${esc(v.label)}</button>`).join("");
  $$("button[data-v]", bar).forEach((b) => (b.onclick = () => api("api/run", common({ variant: b.dataset.v })).then(() => { S.running = true; refreshStatus(true); })));
}
