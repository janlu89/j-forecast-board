/* Timestral demo – front-end (vanilla JS + Plotly). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const C = { white: "#e6e8ee", muted: "#8a90a2", orange: "#ff7a1a", green: "#34d399", blue: "#60a5fa",
  purple: "#a78bfa", red: "#f87171", grey: "#6b7280", grid: "#1f2431", line: "#2a3040", yellow: "#fbbf24" };
const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
const T_COLORS = [C.orange, C.yellow, "#f472b6", "#22d3ee", "#fb923c", "#e879f9"];
const B_COLORS = ["#9ca3af", "#818cf8", "#6b7280", "#94a3b8"];
const PCONF = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] };
const S = { datasets: [], dirty: {}, tab: "overview", series: 0 };

// ------------------------------------------------------------------ utils
async function api(path, body) {
  const opt = body instanceof FormData ? { method: "POST", body }
    : body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const res = await fetch(path, opt);
  if (res.status === 401) { location.reload(); throw new Error("Session expired: please sign in again."); }
  const js = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok || js.error) throw new Error(js.error || res.statusText);
  return js;
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(toast.h); toast.h = setTimeout(() => (t.style.display = "none"), 9000);
}
async function withBusy(el, fn) {
  el.classList.add("busy");
  try { return await fn(); } catch (e) { toast(e.message); console.error(e); } finally { el.classList.remove("busy"); }
}
function fmt(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  if (a >= 10000) return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (a >= 100) return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
  return v.toLocaleString("en-US", { maximumFractionDigits: d });
}
const pct = (v, d = 1) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)}%`);
const spct = (v, d = 1) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%`);
const dur = (s) => (s === null || s === undefined ? "–" : s < 90 ? `${s.toFixed(s < 10 ? 1 : 0)} s` : `${(s / 60).toFixed(1)} min`);
const ms = (s) => Date.parse(String(s).length > 10 ? String(s).replace(" ", "T") : s + "T00:00");
const chip = (label, value, cls = "") => `<span class="chip ${cls}">${label} <b>${value}</b></span>`;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const ds = () => S.datasets.find((d) => d.key === $("#dsSel").value);
const variant = () => $("#varSel").value;
const variantLabel = () => $("#varSel").selectedOptions[0]?.dataset.label || "";

const MET = {
  mape: ["MAPE", (v) => pct(v, 2), "mean absolute % error"], rmspe: ["RMSPE", (v) => pct(v, 2), "Kaggle metric"],
  wape: ["WAPE", (v) => pct(v, 2), "total error / total volume"], smape: ["sMAPE", (v) => pct(v, 2)],
  mase: ["MASE", (v) => fmt(v, 3), "< 1 beats the seasonal naive"], bias: ["Bias", (v) => spct(v, 2), "+ = over-forecast"],
  mae: ["MAE", (v) => fmt(v)], rmse: ["RMSE", (v) => fmt(v)], wql: ["WQL", (v) => pct(v, 2), "quantile loss"],
  coverage: ["Cov. 80%", (v) => pct(v, 1), "target 80%"], width: ["Width 80%", (v) => pct(v, 1), "band width / volume"],
  secs: ["Time", (v) => dur(v)],
};
const mfmt = (k, v) => (MET[k] ? MET[k][1](v) : fmt(v));

function common(extra = {}) {
  const ctx = $("#context").value;
  return { dataset: $("#dsSel").value, horizon: +$("#horizon").value || null, context: ctx === "" ? null : +ctx,
    series: S.series, variant: variant(), ...extra };
}
function layout(extra = {}) {
  const base = {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#0f1218",
    font: { color: "#c9cdd8", family: "Inter, Segoe UI, system-ui, sans-serif", size: 12 },
    margin: { l: 64, r: 18, t: 34, b: 36 },
    xaxis: { gridcolor: C.grid, linecolor: C.line, zeroline: false },
    yaxis: { gridcolor: C.grid, linecolor: C.line, zeroline: false },
    legend: { orientation: "h", x: 0, y: 1.12, bgcolor: "rgba(0,0,0,0)", font: { size: 11.5 }, traceorder: "normal" },
    hovermode: "x unified", hoverlabel: { bgcolor: "#171b24", bordercolor: C.line, font: { color: C.white } },
  };
  for (const k of Object.keys(extra)) base[k] = typeof extra[k] === "object" && !Array.isArray(extra[k]) && base[k] ? { ...base[k], ...extra[k] } : extra[k];
  return base;
}
function band(x, lo, hi, color, name, a = 0.22, legend = true) {
  return [
    { x, y: lo, type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
    { x, y: hi, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: rgba(color, a), name, hoverinfo: "skip", showlegend: legend },
  ];
}
const line = (x, y, color, name, extra = {}) => ({ x, y, type: "scatter", mode: "lines", name, hovertemplate: "%{y:,.2f}", ...extra,
  line: { color, width: 1.6, ...(extra.line || {}) } });
const vline = (x, color, dash = "dash") => ({ type: "line", x0: x, x1: x, yref: "paper", y0: 0, y1: 1, line: { color, width: 1.2, dash } });
const vrect = (x0, x1, color, a) => ({ type: "rect", x0, x1, yref: "paper", y0: 0, y1: 1, fillcolor: rgba(color, a), line: { width: 0 }, layer: "below" });
const label = (x, text, color) => ({ x, y: 1, yref: "paper", text, showarrow: false, xanchor: "left", yanchor: "top", font: { color, size: 11 }, xshift: 4 });
const unitAxis = (u) => ({ title: { text: u, font: { size: 12, color: C.muted } } });

// ------------------------------------------------------------------ boot & global controls
async function boot() {
  S.datasets = await api("api/datasets");
  fillDatasets("rossmann");
  $$("#nav button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  $("#dsSel").onchange = () => onDatasetChange();
  $("#serSel").onchange = () => setSeries(+$("#serSel").value);
  $("#serPrev").onclick = () => setSeries(Math.max(0, S.series - 1));
  $("#serNext").onclick = () => setSeries(Math.min(ds().n - 1, S.series + 1));
  $("#varSel").onchange = onVariantChange;
  $("#horizon").onchange = $("#context").onchange = () => { S.statusKey = null; refreshStatus(true).then(markAll); };
  initSeries(); initExplore(); initLive(); initSplit(); initWhatIf(); initAnomalies(); initPlanner(); initChat(); initUpload(); renderAbout();
  await onDatasetChange();
  setInterval(() => refreshStatus(false), 2500);
}
function fillDatasets(sel) {
  $("#dsSel").innerHTML = S.datasets.map((d) => `<option value="${d.key}">${esc(d.name)}</option>`).join("");
  if (sel && S.datasets.some((d) => d.key === sel)) $("#dsSel").value = sel;
}
async function onDatasetChange() {
  const d = ds();
  S.series = 0;
  $("#horizon").value = d.horizon;
  $("#context").value = d.context || 0;
  $("#adStep").value = d.season;
  for (const id of ["#spStart", "#spSplit", "#spEnd"]) $(id).value = "";
  S.sp = null;
  $("#serCtl").style.display = d.n > 1 ? "" : "none";
  $("#serLabel").textContent = d.id_label;
  $("#serSel").innerHTML = d.ids.map((id, i) => `<option value="${i}">${esc(id)}</option>`).join("");
  $("#nav [data-tab=total]").style.display = d.n > 1 ? "" : "none";
  if (S.tab === "total" && d.n < 2) S.tab = "overview";
  S.statusKey = null; S.wi = null;
  await refreshStatus(true);
  markAll();
  chatContextLine();
}
function setSeries(i) {
  S.series = i; $("#serSel").value = i;
  for (const t of ["series", "explore", "live", "split", "whatif", "anomalies", "planner"]) S.dirty[t] = true;
  S.wi = null; stopPlay(); refreshTab(); chatContextLine();
}
function onVariantChange() {
  const o = $("#varSel").selectedOptions[0];
  if (o && o.dataset.done !== "1") {
    api("api/run", common({ variant: o.value })).then(() => refreshStatus(true)).catch((e) => toast(e.message));
  }
  S.chosen = variant();
  brand(); markAll();
}
function brand() {
  $("#brandModel").textContent = (variantLabel() || "Timestral").split(" · ")[0];
  $("#brandData").textContent = ds().name;
}
function markAll() {
  for (const t of ["overview", "series", "total", "explore", "live", "split", "whatif", "anomalies", "planner"]) S.dirty[t] = true;
  stopPlay(); refreshTab();
}
async function refreshStatus(force) {
  const d = ds(); if (!d) return;
  if (!force && !S.running) return;
  let st;
  try { st = await api("api/status", common()); } catch (e) { return; }
  const key = `${d.key}|${st.H}|${st.L}`;
  const doneNow = st.variants.filter((v) => v.done).map((v) => v.key).join(",");
  const changed = S.statusKey === key && S.doneKeys !== doneNow;
  S.statusKey = key; S.doneKeys = doneNow; S.status = st; S.running = st.any_running;
  // model selector: computed variants first
  const keep = S.chosen || variant();
  const vs = [...st.variants].sort((a, b) => (b.done - a.done));
  $("#varSel").innerHTML = vs.map((v) => `<option value="${v.key}" data-done="${v.done ? 1 : 0}" data-label="${esc(v.label)}">${esc(v.label)}${
    v.done ? "" : v.state === "running" ? ` – running ${pct(v.progress, 0)}` : v.state === "queued" ? " – queued" : " – not computed (select to run)"}</option>`).join("");
  const firstDone = vs.find((v) => v.done);
  $("#varSel").value = vs.some((v) => v.key === keep) ? keep : (firstDone ? firstDone.key : vs[0].key);
  brand();
  const run = st.variants.filter((v) => v.state === "running" || v.state === "queued");
  const pill = $("#jobPill");
  if (run.length) {
    const r = run.find((v) => v.state === "running") || run[0];
    pill.hidden = false;
    pill.innerHTML = `⏳ ${esc(r.label)} on ${d.n.toLocaleString("en-US")} series ${r.state === "running" ? pct(r.progress, 0) : "queued"}${r.eta ? ` · ~${dur(r.eta)} left` : ""}${run.length > 1 ? ` · +${run.length - 1} queued` : ""}`;
  } else pill.hidden = true;
  const err = st.variants.find((v) => v.state === "error");
  if (err && !S.errShown) { S.errShown = true; toast(`${err.label}: ${err.error}`); }
  if (changed) markAll();
  else if (S.tab === "overview" && $("#ovOut .runbar")) renderRunbar();
}
function showTab(t) {
  S.tab = t;
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${t}`));
  refreshTab();
  chatContextLine();
  window.dispatchEvent(new Event("resize"));
}
function refreshTab() {
  const t = S.tab;
  if (!S.dirty[t]) return;
  S.dirty[t] = false;
  const hasResults = S.status && S.status.variants.some((v) => v.done);
  if (["overview", "series", "total", "planner"].includes(t) && !hasResults) return waitingFor(t);
  if (t === "overview") runOverview();
  if (t === "series") runSeries();
  if (t === "total") runTotal();
  if (t === "explore" && S.rp) runExplore();
  if (t === "live") runLive();
  if (t === "split" && S.sp) runSplit();
  if (t === "whatif") runWhatIf(true);
  if (t === "anomalies" && S.ad) runAnomalies();
  if (t === "planner") runPlanner();
}
function waitingFor(t) {
  S.dirty[t] = true;
  const msg = `<div class="empty">⏳ Timestral is evaluating <b>${esc(ds().name)}</b> in the background (first run only – results are cached on disk).<br>Progress is shown at the top right; this page updates by itself.</div>`;
  if (t === "overview") $("#ovOut").innerHTML = msg;
  if (t === "series") $("#seChips").innerHTML = msg;
  if (t === "total") $("#toChips").innerHTML = msg;
  if (t === "planner") $("#plChips").innerHTML = msg;
}

// ================================================================== OVERVIEW
async function runOverview() {
  await withBusy($("#ovOut"), async () => { S.ov = await api("api/overview", common()); renderOverview(S.ov); });
}
function bestCols(rows, keys) {
  const best = {};
  for (const k of keys) {
    const vals = rows.map((r) => r[k]).filter((v) => v !== null && v !== undefined);
    if (!vals.length) continue;
    best[k] = k === "bias" ? vals.reduce((a, b) => (Math.abs(b) < Math.abs(a) ? b : a))
      : k === "coverage" ? vals.reduce((a, b) => (Math.abs(b - 0.8) < Math.abs(a - 0.8) ? b : a)) : Math.min(...vals);
  }
  return best;
}
function metricTable(rows, keys, opts = {}) {
  const best = bestCols(rows, keys.filter((k) => k !== "secs"));
  return `<div class="scroll" style="max-height:none"><table><thead><tr><th>Model</th>${keys.map((k) => `<th title="${MET[k]?.[2] || ""}">${MET[k]?.[0] || k}</th>`).join("")}</tr></thead><tbody>${
    rows.map((r, i) => `<tr class="${r.kind === "timestral" ? "t" : ""} ${i === 0 && opts.first ? "best" : ""}"><td>${esc(r.name)}${i === 0 && opts.first ? " 🏆" : ""}</td>${
      keys.map((k) => `<td class="${best[k] !== undefined && r[k] === best[k] ? "bestcell" : ""}">${r[k] === null || r[k] === undefined ? "–" : mfmt(k, r[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function renderOverview(o) {
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
function bwTable(rows, title, P) {
  return `<div><div class="note" style="margin-bottom:4px">${title}</div><table><thead><tr><th>${esc(ds().id_label)}</th><th>Timestral</th><th>Baseline</th></tr></thead><tbody>${
    rows.map((r) => `<tr class="click" data-i="${r.index}"><td>#${esc(r.id)}</td><td>${mfmt(P, r.model)}</td><td>${mfmt(P, r.baseline)}</td></tr>`).join("")}</tbody></table></div>`;
}
function renderRunbar() {
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

// ================================================================== SERIES
function initSeries() {
  $$("#tab-series [data-view]").forEach((b) => (b.onclick = () => {
    $$("#tab-series [data-view]").forEach((x) => x.classList.toggle("active", x === b)); S.view = b.dataset.view; applyView();
  }));
  S.view = "recent";
  $("#seBaseline").onchange = () => S.se && Plotly.restyle("sePlot", { visible: $("#seBaseline").checked }, S.seBaseIdx);
  $("#seCsv").onclick = () => {
    const r = S.se; if (!r?.future) return;
    const f = r.future;
    const rows = ["date,forecast,p10,p90,p5,p95", ...r.future_dates.map((d, i) => `${d},${f.median[i]},${f.lo[i]},${f.hi[i]},${f.lo90[i]},${f.hi90[i]}`)];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows.join("\n")], { type: "text/csv" }));
    a.download = `timestral_${r.meta.key}_${r.id}.csv`; a.click();
  };
}
async function runSeries() {
  await withBusy($("#seCard"), async () => { S.se = await api("api/series", common()); renderSeries(S.se); });
}
function renderSeries(r) {
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
function onSeRelayout(ev) {
  if (S.seSync) return;
  let rg = ev["xaxis.range"] || (ev["xaxis.range[0]"] !== undefined ? [ev["xaxis.range[0]"], ev["xaxis.range[1]"]] : null);
  if (ev["xaxis.autorange"]) rg = [S.seBounds.first, S.seBounds.last];
  if (rg) setSeRange(rg);
}
function applyView() {
  if (!S.seBounds) return;
  const b = S.seBounds;
  const start = S.view === "all" ? b.first : S.view === "year"
    ? new Date(Math.max(ms(b.first), ms(b.last) - 365 * 864e5)).toISOString().slice(0, 16).replace("T", " ") : b.recent;
  setSeRange([start, b.last]);
}
function setSeRange(rg) {
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
function renderCovariates(r) {
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

// ================================================================== TOTAL
async function runTotal() {
  if (ds().n < 2) return;
  await withBusy($("#toCard"), async () => { const r = await api("api/total", common()); S.to = r; renderTotal(r); });
}
function renderTotal(r) {
  const T = r.dates.length, H = r.H, last = r.dates[T - 1], fd = r.future_dates;
  const tr = [line(r.dates, r.y, C.white, "actual total", { line: { width: 1.1 } })];
  const shapes = [vrect(r.dates[r.cuts[0]], last, C.orange, 0.07), vline(r.dates[r.cuts[0]], C.orange), vrect(last, fd.at(-1), C.green, 0.05), vline(last, C.green)];
  r.cuts.forEach((c, w) => {
    const x = r.dates.slice(c, c + H);
    if (r.direct) {
      tr.push(...band(x, r.direct.holdout[w].lo, r.direct.holdout[w].hi, C.purple, "direct 80%", 0.18, w === 0));
      tr.push(line(x, r.direct.holdout[w].median, C.purple, "direct (model on the total)", { line: { width: 1.4, dash: "dash" }, showlegend: w === 0 }));
    }
    if (r.bottom_up) tr.push(line(x, r.bottom_up.holdout[w], C.orange, "bottom-up (sum of series forecasts)", { line: { width: 2.2 }, showlegend: w === 0 }));
  });
  if (r.bottom_up) {
    const fx = [last, ...fd], j = (a) => [r.y[T - 1], ...a];
    if (r.direct) tr.push(...band(fx, j(r.direct.future.lo), j(r.direct.future.hi), C.purple, "direct 80% (future)", 0.14, false),
      line(fx, j(r.direct.future.median), C.purple, "direct", { line: { width: 1.4, dash: "dash" }, showlegend: false }));
    tr.push(line(fx, j(r.bottom_up.future), C.green, "bottom-up (future)", { line: { width: 2.2 } }));
  }
  const start = r.dates[Math.max(0, r.cuts[0] - 5 * H)];
  Plotly.react("toPlot", tr, layout({ shapes, annotations: [label(r.dates[r.cuts[0]], "holdout", C.orange), label(last, "future", C.green)],
    yaxis: unitAxis(`total ${r.meta.unit}`), margin: { l: 70, r: 18, t: 44, b: 10 },
    xaxis: { range: [start, fd.at(-1)], rangeslider: { visible: true, thickness: 0.08, bgcolor: "#0b0d12", bordercolor: "#232838", borderwidth: 1 } } }), PCONF);
  const best = r.table[0];
  $("#toChips").innerHTML = chip("Series summed", r.meta.n.toLocaleString("en-US")) + (best ? chip("Best on total", `${esc(best.name)} · MAPE ${pct(best.mape, 2)}`, "good") : "") +
    (r.model ? chip("Bottom-up model", esc(r.model)) : "");
  $("#toTable").innerHTML = metricTable(r.table, ["mape", "wape", "bias", "mae", "rmse", "coverage"], { first: true });
}

// ================================================================== EXPLORE (replay)
function initExplore() {
  $("#rpRun").onclick = runExplore;
  $("#rpSlider").oninput = () => { stopPlay(); drawFrame(+$("#rpSlider").value); };
  $("#rpReveal").onchange = $("#rpFollow").onchange = () => S.rp && drawFrame(S.rpK);
  $("#rpPlay").onclick = () => (S.rpTimer ? stopPlay() : startPlay());
  $("#rpSpeed").onchange = () => { if (S.rpTimer) { stopPlay(); startPlay(); } };
}
async function runExplore() {
  stopPlay(); S.dirty.explore = false;
  await withBusy($("#rpCard"), async () => {
    const mult = +$("#rpSpan").value, H = +$("#horizon").value || ds().horizon;
    const r = await api("api/replay", common({ frames: +$("#rpFrames").value, span: mult ? mult * H : null }));
    S.rp = r;
    r.all = [...r.dates, ...r.future_dates];
    r.start = Math.max(0, r.frames[0].cut - Math.max(3 * r.horizon, 4 * r.meta.season));
    let lo = Infinity, hi = -Infinity;
    const u = (v) => { if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } };
    r.y.slice(r.start).forEach(u); r.frames.forEach((f) => { f.lo.forEach(u); f.hi.forEach(u); });
    r.yr = [lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.06];
    const sl = $("#rpSlider"); sl.max = r.frames.length - 1; sl.disabled = false; sl.value = 0;
    $("#rpPlot").innerHTML = "";
    drawFrame(0); drawReplayErrors();
  });
}
function drawFrame(k) {
  const r = S.rp; if (!r) return;
  S.rpK = k; $("#rpSlider").value = k;
  const f = r.frames[k], H = r.horizon, c = f.cut, T = r.dates.length, today = r.all[c - 1];
  const fx = [today, ...r.all.slice(c, c + H)], j = (a) => [r.y[c - 1], ...a];
  const tr = [line(r.dates.slice(r.start, c), r.y.slice(r.start, c), C.white, "data seen by the model", { line: { width: 1.2 } })];
  if ($("#rpReveal").checked && c < T) tr.push(line(r.dates.slice(c), r.y.slice(c), "#5b6275", "hidden data (truth)", { line: { width: 1.2, dash: "dot" } }));
  tr.push(...band(fx, j(f.lo), j(f.hi), C.green, "80% band"), line(fx, j(f.median), C.green, `${r.model.split(" · ")[0]} forecast`, { line: { width: 2.2 } }));
  const follow = $("#rpFollow").checked;
  const x0 = follow ? r.all[Math.max(r.start, c - 3 * H)] : r.all[r.start];
  const x1 = follow ? r.all[Math.min(r.all.length - 1, c + H)] : r.all.at(-1);
  Plotly.react("rpPlot", tr, layout({ shapes: [vline(today, C.white), vrect(today, r.all[Math.min(r.all.length - 1, c + H - 1)], C.green, 0.05)],
    annotations: [label(today, `today · ${today}`, C.white)], xaxis: { range: [x0, x1] }, yaxis: { range: r.yr, ...unitAxis(r.meta.unit) }, margin: { l: 64, r: 18, t: 44, b: 36 } }), PCONF);
  const P = r.meta.primary;
  $("#rpWhen").textContent = `${k + 1}/${r.frames.length} · ${today}`;
  $("#rpChips").innerHTML = [chip(r.meta.n > 1 ? r.meta.id_label : "Series", `#${esc(r.id)}`), chip("Today", today), chip("Model", esc(r.model)),
    f.err !== undefined ? chip(`${MET[P][0]} vs truth`, mfmt(P, f.err)) : chip("Truth", "not available yet (real future)"),
    f.coverage !== undefined ? chip("Cov. 80%", pct(f.coverage, 0), f.coverage >= 0.7 ? "good" : "warn") : "",
    chip("Compute (all frames)", dur(r.seconds))].join("");
  if (S.rpErrDrawn) Plotly.restyle("rpErr", { "marker.color": [r.frames.map((_, i) => (i === k ? C.orange : "#3a4155"))] }, [0]);
}
function drawReplayErrors() {
  const r = S.rp, P = r.meta.primary;
  Plotly.react("rpErr", [{ x: r.frames.map((f) => r.all[f.cut - 1]), y: r.frames.map((f) => f.err ?? null), type: "bar",
    marker: { color: r.frames.map((_, i) => (i === S.rpK ? C.orange : "#3a4155")) }, hovertemplate: `today %{x}<br>${MET[P][0]} %{y${P === "mase" ? ":.3f" : ":.2%"}}<extra></extra>` }],
  layout({ margin: { l: 64, r: 18, t: 8, b: 30 }, showlegend: false, hovermode: "closest", bargap: 0.25, yaxis: P === "mase" ? {} : { tickformat: ".0%" } }), { ...PCONF, displayModeBar: false });
  S.rpErrDrawn = true;
  const el = $("#rpErr"); el.removeAllListeners?.("plotly_click"); el.on("plotly_click", (ev) => { stopPlay(); drawFrame(ev.points[0].pointIndex); });
}
function startPlay() {
  if (!S.rp) return;
  if (S.rpK >= S.rp.frames.length - 1) S.rpK = -1;
  $("#rpPlay").textContent = "❚❚";
  S.rpTimer = setInterval(() => { if (S.rpK >= S.rp.frames.length - 1) return stopPlay(); drawFrame(S.rpK + 1); }, +$("#rpSpeed").value);
}
function stopPlay() { clearInterval(S.rpTimer); S.rpTimer = null; $("#rpPlay").textContent = "▶"; }

// ================================================================== LIVE
function initLive() {
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
const stepMs = () => ({ h: 3600e3, D: 864e5, "7D": 7 * 864e5, MS: 30.4 * 864e5 }[ds().freq] || 864e5);
async function runLive() {
  S.dirty.live = false;
  await withBusy($("#lvCard"), async () => {
    const r = await api("api/live", common({ origin: $("#lvDate").value || null }));
    S.lv = r;
    $("#lvPlot .empty")?.remove();
    renderLive(r);
  });
}
/** Forecast chart of an api/live result (also used by the chat). Returns the forecast origin date. */
function drawLive(el, r, extra = {}) {
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
function renderLive(r) {
  $("#lvDate").min = r.first.slice(0, 10); $("#lvDate").max = r.last.slice(0, 10);
  if (!$("#lvDate").value) $("#lvDate").placeholder = r.last.slice(0, 10);
  const today = drawLive("lvPlot", r);
  const m = r.metrics, P = r.meta.primary;
  $("#lvChips").innerHTML = [chip(r.meta.n > 1 ? r.meta.id_label : "Series", `#${esc(r.id)}`), chip("From", today), chip("Horizon", `${r.horizon} steps`), chip("Model", esc(r.model)),
    m && m[P] !== undefined ? chip(`${MET[P][0]} vs reality`, mfmt(P, m[P]), "good") + chip("Cov. 80%", pct(m.coverage, 0)) + chip("Bias", spct(m.bias)) : chip("Reality", "not known yet – true forecast"),
    chip("Compute", dur(r.seconds))].join("");
}

// ================================================================== SPLIT TEST
function initSplit() {
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
const iso = (d) => d.toISOString().slice(0, 10);
async function runSplit() {
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
function renderSplit(r) {
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

// ================================================================== WHAT-IF
const WI_PRESETS = {
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
function initWhatIf() {
  $("#wiRun").onclick = () => runWhatIf(false);
  $("#wiReset").onclick = () => { $$(".wi-row .mode").forEach((m) => (m.value = "keep")); runWhatIf(false); };
}
function readEdits() {
  return $$(".wi-row").map((row) => ({ name: row.dataset.name, mode: row.querySelector(".mode").value, value: +row.querySelector(".val").value,
    start: +row.querySelector(".from").value, end: +row.querySelector(".to").value })).filter((e) => e.mode !== "keep");
}
async function runWhatIf(initial) {
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
function buildWhatIfRows(r) {
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
function drawWhatIf(el, r, extra = {}) {
  const last = r.dates.length - 1, fx = [r.dates[last], ...r.future_dates], j = (a) => [r.y[last], ...a];
  const changed = JSON.stringify(r.base.median) !== JSON.stringify(r.scenario.median);
  const tr = [line(r.dates, r.y, C.white, "actual", { line: { width: 1.2 } }), ...band(fx, j(r.base.lo), j(r.base.hi), C.green, "base 80%", 0.16),
    line(fx, j(r.base.median), C.green, "base forecast", { line: { width: 2 } })];
  if (changed) tr.push(...band(fx, j(r.scenario.lo), j(r.scenario.hi), C.purple, "scenario 80%", 0.2), line(fx, j(r.scenario.median), C.purple, "scenario", { line: { width: 2.2 } }));
  Plotly.react(el, tr, layout({ shapes: [vline(r.dates[last], C.green)], annotations: [label(r.dates[last], "future", C.green)], yaxis: unitAxis(r.meta.unit), ...extra }), PCONF);
}
function renderWhatIf(r) {
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

// ================================================================== ANOMALIES
function initAnomalies() { $("#adRun").onclick = runAnomalies; }
async function runAnomalies() {
  S.dirty.anomalies = false;
  await withBusy($("#adCard"), async () => {
    const r = await api("api/anomalies", common({ step: +$("#adStep").value || null, windows: +$("#adWin").value, level: +$("#adLevel").value }));
    S.ad = r; renderAnomalies(r);
  });
}
function renderAnomalies(r) {
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

// ================================================================== ORDER PLANNER
function initPlanner() {
  $("#plRun").onclick = runPlanner;
  for (const id of ["#plTarget", "#plScope"]) $(id).onchange = runPlanner;
}
async function runPlanner() {
  S.dirty.planner = false;
  await withBusy($("#plCard"), async () => {
    const r = await api("api/planner", common({ scope: $("#plScope").value, target: +$("#plTarget").value,
      margin: (+$("#plMargin").value || 40) / 100, holding: (+$("#plHold").value || 0) / 100 }));
    S.pl = r; renderPlanner(r);
  });
}
const plLevel = (lv) => (lv === null || lv === undefined ? "–" : `P${Math.round(lv * 100)}`);
const plBuffer = (k) => (k === null || k === undefined ? "–" : `${k >= 1 ? "+" : "−"}${Math.abs(Math.round((k - 1) * 100))}%`);
/** Availability vs leftover stock for both policies (also used by the chat). */
function drawPlannerCurve(el, r, extra = {}) {
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
function renderPlanner(r) {
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

// ================================================================== CHAT (Claude CLI + forecasting tools)
// The chat is a side panel available on every tab: each question carries what the user is looking at.
const TAB_NAMES = { overview: "Overview", series: "Series", total: "Total", explore: "Explore backtest", live: "Live forecast",
  split: "Split test", whatif: "What-if", anomalies: "Anomalies", planner: "Order planner", upload: "Your data", about: "About" };
const TAB_STATE = { overview: "ov", series: "se", total: "to", explore: "rp", live: "lv", split: "sp", whatif: "wi", anomalies: "ad", planner: "pl" };
const CHAT_SUGGEST = {
  overview: ["Is this accuracy good enough for a retailer?", "What does the 80% band coverage tell me here?"],
  series: ["Why does the forecast for this series look like this?", "Can I trust the forecast for the next weeks?"],
  total: ["Why is the total easier to forecast than single series?"],
  explore: ["How well did the forecast follow reality here?"],
  live: ["How good is this forecast against what really happened?", "Explain the uncertainty band in business terms."],
  split: ["Does the accuracy drop the further it forecasts?"],
  whatif: ["Is this scenario effect believable?"],
  anomalies: ["What could have caused these anomalies?"],
  planner: ["What do these numbers mean in money for a retailer?", "Which order level should we use, and why?"],
  upload: ["What format should my CSV have?"],
  about: ["Can we use Timestral for our retail clients? What about licensing?"],
};
function initChat() {
  S.chat = { history: [], busy: false };
  $("#chatFab").onclick = () => toggleChat(true);
  $("#chatClose").onclick = () => toggleChat(false);
  $("#chatForm").onsubmit = (e) => { e.preventDefault(); sendChat(); };
  $("#chatIn").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#chatDrawer").hidden && !$("#agentModal").open) toggleChat(false); });
  initAgents();
}

// ------------------------------------------------------------------ agent choice (Claude CLI, GPT, local, other API)
function initAgents() {
  $("#agentBtn").onclick = openAgentModal;
  $("#agentX").onclick = $("#agentCancel").onclick = () => $("#agentModal").close();
  $("#agentForm").onsubmit = (e) => { e.preventDefault(); saveAgents(); };
  loadAgents();
}
async function loadAgents() {
  try { S.agents = await api("api/agents"); } catch (e) { return; }
  const a = S.agents.agents.find((x) => x.id === S.agents.active);
  $("#agentName").textContent = a ? `${a.name}${a.model ? ` · ${a.model}` : ""}` : "Agent";
  $("#agentDot").className = `dot ${a && a.configured ? "ok" : "warn"}`;
}
function agentFields(a) {
  const id = (f) => `ag_${a.id}_${f}`;
  if (a.kind === "claude-cli") {
    return `<label class="fld"><span>Model</span><select id="${id("model")}" data-f="model">${a.models.map((m) =>
      `<option ${m === a.model ? "selected" : ""}>${esc(m)}</option>`).join("")}</select></label>`;
  }
  const keyPh = a.has_key ? `saved (${a.key_hint}) – leave empty to keep` : a.id === "local" ? "usually not needed" : "paste the API key";
  return `<label class="fld"><span>Base URL</span><input type="text" id="${id("base_url")}" data-f="base_url" value="${esc(a.base_url || "")}"
      placeholder="https://…/v1" spellcheck="false" autocomplete="off"></label>
    <div class="fld"><label for="${id("model")}">Model</label><div class="modelrow">
      <select id="${id("model")}" data-f="model">${modelOptions(a.model ? [a.model] : [], a.model)}</select>
      <button type="button" data-load="${a.id}" title="Ask the API for its model list">↻ Load models</button></div></div>
    <label class="fld manual" hidden><span>Model id</span><input type="text" id="${id("manual")}" data-f="model_manual" placeholder="type the model id"
      spellcheck="false" autocomplete="off"></label>
    <label class="fld"><span>API key</span><input type="password" id="${id("api_key")}" data-f="api_key" placeholder="${esc(keyPh)}" autocomplete="new-password"></label>
    ${a.has_key ? `<label class="note chk"><input type="checkbox" data-f="clear_key"> remove the saved key</label>` : ""}`;
}
// Speech, moderation and embedding models cannot chat: list them last.
const NON_CHAT = /whisper|tts|speech|audio|guard|embed|moderation|rerank|playai|transcri|dall-e|image|vision-only/i;
function modelOptions(models, current) {
  const chat = models.filter((m) => !NON_CHAT.test(m)), other = models.filter((m) => NON_CHAT.test(m));
  const opt = (m) => `<option value="${esc(m)}" ${m === current ? "selected" : ""}>${esc(m)}</option>`;
  const head = `<option value="" ${current ? "" : "selected"}>${models.length ? "— choose a model —" : "— press ↻ Load models —"}</option>`;
  return head + chat.map(opt).join("") + (other.length ? `<optgroup label="Probably not for chat">${other.map(opt).join("")}</optgroup>` : "")
    + `<option value="__manual__">✎ Type a model id…</option>`;
}
function openAgentModal() {
  if (!S.agents) return;
  const active = S.agents.active;
  $("#agentList").innerHTML = S.agents.agents.map((a) => `
    <div class="agentcard ${a.id === active ? "sel" : ""}" data-id="${a.id}">
      <label class="agenthd"><input type="radio" name="agent" value="${a.id}" ${a.id === active ? "checked" : ""}>
        <span><b>${esc(a.name)}</b> <span class="note">· ${esc(a.vendor)}</span>${a.id === active ? ' <span class="tag done">in use</span>' : ""}</span></label>
      <div class="note">${esc(a.help)}</div>
      <div class="agentbody">${agentFields(a)}
        <div class="agenttest"><button type="button" data-test="${a.id}">Test connection</button><span class="note" data-res="${a.id}"></span></div>
      </div>
    </div>`).join("");
  S.agentModels = S.agentModels || {};
  // Load the model list by itself once an API agent is selected and has what it needs (never starts a local server).
  const autoLoad = (id) => {
    const a = S.agents.agents.find((x) => x.id === id), f = a.kind === "openai" && readAgent(id);
    if (!f || S.agentModels[id] || !f.base_url || !(a.has_key || f.api_key || id === "local")) return;
    S.agentModels[id] = []; testAgent(id);
  };
  const select = (id) => { $$("#agentList .agentcard").forEach((c) => c.classList.toggle("sel", c.dataset.id === id)); autoLoad(id); };
  $$("#agentList input[name=agent]").forEach((r) => (r.onchange = () => select(r.value)));
  $$("#agentList .agentcard").forEach((c) => (c.onfocusin = () => {
    const r = c.querySelector("input[name=agent]"); if (!r.checked) { r.checked = true; select(c.dataset.id); }
  }));
  $$("#agentList [data-test]").forEach((b) => (b.onclick = () => testAgent(b.dataset.test)));
  $$("#agentList [data-load]").forEach((b) => (b.onclick = () => testAgent(b.dataset.load)));
  $$("#agentList select[data-f=model]").forEach((sel) => (sel.onchange = () => {
    const man = sel.closest(".agentbody").querySelector(".fld.manual");
    if (man) { man.hidden = sel.value !== "__manual__"; if (!man.hidden) man.querySelector("input").focus(); }
  }));
  // A pasted key: fetch the list as soon as the field is left.
  $$("#agentList input[data-f=api_key]").forEach((inp) => (inp.onchange = () => {
    const id = inp.closest(".agentcard").dataset.id; if (inp.value.trim()) { S.agentModels[id] = []; testAgent(id); }
  }));
  const cached = Object.entries(S.agentModels).filter(([, m]) => m.length);
  for (const [id, models] of cached) { const sel = $(`#ag_${id}_model`); if (sel) sel.innerHTML = modelOptions(models, sel.value); }
  $$("#agentList input[data-f=base_url]").forEach((inp) => (inp.onchange = () => { delete S.agentModels[inp.closest(".agentcard").dataset.id]; }));
  $("#agentMsg").textContent = "";
  $("#agentModal").showModal();
  autoLoad(active);
}
function readAgent(id) {
  const card = $(`#agentList .agentcard[data-id="${id}"]`), out = { id };
  card.querySelectorAll("[data-f]").forEach((el) => { out[el.dataset.f] = el.type === "checkbox" ? el.checked : el.value.trim(); });
  if (out.model === "__manual__") out.model = out.model_manual || "";
  delete out.model_manual;
  return out;
}
async function testAgent(id) {
  const res = $(`#agentList [data-res="${id}"]`), btns = $$(`#agentList [data-test="${id}"], #agentList [data-load="${id}"]`);
  res.className = "note"; res.textContent = "Connecting…"; btns.forEach((b) => (b.disabled = true));
  try {
    const r = await api("api/agents/test", readAgent(id));
    res.className = `note ${r.ok ? "okc" : "errc"}`; res.textContent = r.message;
    const sel = $(`#ag_${id}_model`);
    if (sel && sel.tagName === "SELECT" && r.models && r.models.length) {
      const cur = readAgent(id).model;
      sel.innerHTML = modelOptions(r.models, cur);
      S.agentModels[id] = r.models;
      if (!sel.value) { res.textContent = `${r.message} Now choose the model in the list.`; sel.focus(); }
    }
  } catch (e) { res.className = "note errc"; res.textContent = e.message; } finally { btns.forEach((b) => (b.disabled = false)); }
}
async function saveAgents() {
  const chosen = $("#agentList input[name=agent]:checked")?.value;
  if (!chosen) return;
  $("#agentSave").disabled = true; $("#agentMsg").className = "note"; $("#agentMsg").textContent = "Saving…";
  try {
    for (const a of S.agents.agents) {  // keep the edits made to the other agents too
      const f = readAgent(a.id);
      const orig = { model: a.model || "", base_url: a.base_url || "" };
      const changed = f.id === chosen || f.api_key || f.clear_key || (f.model ?? orig.model) !== orig.model || (f.base_url ?? orig.base_url) !== orig.base_url;
      if (changed) S.agents = await api("api/agents", { ...f, api_key: f.api_key || null, activate: f.id === chosen });
    }
    await loadAgents();
    $("#agentModal").close();
    const a = S.agents.agents.find((x) => x.id === S.agents.active);
    toastOk(`Chat agent: ${a.name}${a.model ? ` · ${a.model}` : ""}`);
  } catch (e) { $("#agentMsg").className = "note errc"; $("#agentMsg").textContent = e.message; } finally { $("#agentSave").disabled = false; }
}
function toastOk(msg) { toast(msg); $("#toast").classList.add("ok"); setTimeout(() => $("#toast").classList.remove("ok"), 9000); }
function toggleChat(open) {
  $("#chatDrawer").hidden = !open;
  $("#chatFab").hidden = open;
  $("#chatFab").setAttribute("aria-expanded", String(open));
  document.body.classList.toggle("chat-open", open);
  if (open) { chatContextLine(); $("#chatIn").focus(); }
  window.dispatchEvent(new Event("resize"));  // charts reflow to the narrower page
}
function chatContextLine() {
  if ($("#chatDrawer").hidden) return;
  const d = ds(), t = S.tab;
  $("#chatCtx").textContent = [TAB_NAMES[t] || t, d?.name, d && d.n > 1 ? `${d.id_label} #${d.ids[S.series]}` : null].filter(Boolean).join(" · ");
  const sug = ["Explain what this page shows.", ...(CHAT_SUGGEST[t] || [])];
  $("#chatSuggest").innerHTML = sug.map((q) => `<button type="button" class="sugg">${esc(q)}</button>`).join("");
  $$("#chatSuggest .sugg").forEach((b) => (b.onclick = () => { $("#chatIn").value = b.textContent; sendChat(); }));
}
/** Compact copy of a result object for the assistant: long series become min/max/mean/first/last. */
function compact(v, depth = 0) {
  if (Array.isArray(v)) {
    if (v.length > 24 && v.every((x) => x === null || typeof x === "number")) {
      const f = v.filter((x) => x !== null);
      return f.length ? { n: v.length, first: f[0], last: f.at(-1), min: Math.min(...f), max: Math.max(...f),
        mean: +(f.reduce((a, b) => a + b, 0) / f.length).toFixed(3) } : { n: v.length };
    }
    if (v.length > 24 && v.every((x) => typeof x === "string")) return { n: v.length, first: v[0], last: v.at(-1) };
    const head = v.slice(0, 12).map((x) => compact(x, depth + 1));
    return v.length > 12 ? [...head, `… +${v.length - 12} more`] : head;
  }
  if (v && typeof v === "object") {
    if (depth > 4) return "…";
    const o = {};
    for (const [k, x] of Object.entries(v)) if (!["ids", "description"].includes(k)) o[k] = compact(x, depth + 1);
    return o;
  }
  return v;
}
/** What the user is looking at: settings, visible text (numbers, KPIs, tables) and the chart data, compacted. */
function pageContext() {
  const d = ds(), t = S.tab, sec = $(`#tab-${t}`);
  let text = "";
  if (sec) {
    const c = sec.cloneNode(true);
    c.querySelectorAll(".plot, script, select, input, button").forEach((n) => n.remove());
    text = c.innerText || c.textContent || "";
    text = text.replace(/[ \t]+/g, " ").replace(/\n\s*\n+/g, "\n").trim().slice(0, 7000);
  }
  const st = TAB_STATE[t] && S[TAB_STATE[t]];
  return { tab: TAB_NAMES[t] || t, dataset: d?.key, dataset_name: d?.name, series: S.series, series_id: d?.ids[S.series],
    series_label: d?.id_label, model: variantLabel(), horizon: +$("#horizon").value || null, context_length: $("#context").value,
    page_text: text, page_data: st ? JSON.stringify(compact(st)).slice(0, 6000) : null };
}
/** Tiny Markdown renderer (escapes HTML first): paragraphs, lists, tables, headings, code, bold, italic, links. */
function md(src) {
  const inline = (t) => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>").replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const out = [], lines = String(src).split("\n");
  for (let i = 0; i < lines.length;) {
    const l = lines[i];
    if (/^```/.test(l)) { const buf = []; i++; while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]); i++; out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`); continue; }
    if (/^\s*\|.*\|\s*$/.test(l)) {
      const rows = []; while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const body = rows.filter((r) => !/^\s*\|[\s:|-]+\|\s*$/.test(r));
      out.push(`<table><thead><tr>${cells(body[0]).map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${
        body.slice(1).map((r) => `<tr>${cells(r).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`); continue;
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(l)) {
      const ordered = /^\s*\d+\./.test(l), items = [];
      const itemRe = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*]\s+/;
      while (i < lines.length && itemRe.test(lines[i])) items.push(lines[i++].replace(itemRe, ""));
      out.push(`<${ordered ? "ol" : "ul"}>${items.map((x) => `<li>${inline(x)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`); continue;
    }
    const h = l.match(/^(#{1,4})\s+(.*)/);
    if (h) { out.push(`<h4>${inline(h[2])}</h4>`); i++; continue; }
    if (!l.trim()) { i++; continue; }
    // always consume the current line (e.g. a half-received table row "| a | b" while streaming), or the loop never advances
    const buf = [lines[i++]]; while (i < lines.length && lines[i].trim() && !/^(```|\s*\||\s*([-*]|\d+\.)\s+|#{1,4}\s)/.test(lines[i])) buf.push(lines[i++]);
    out.push(`<p>${buf.map(inline).join("<br>")}</p>`);
  }
  return out.join("");
}
function chatBubble(role, html = "") {
  const d = document.createElement("div");
  d.className = `msg ${role}`; d.innerHTML = html;
  $("#chatLog").appendChild(d); $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
  return d;
}
function chatChart(host, ch) {
  const box = document.createElement("div");
  box.className = "chatchart";
  box.innerHTML = `<div class="ct">${esc(ch.title)}</div><div class="plot" style="height:300px"></div>`;
  host.appendChild(box);
  const el = box.querySelector(".plot"), small = { margin: { l: 56, r: 12, t: 30, b: 34 } }, r = ch.data;
  try {
    if (ch.kind === "forecast") drawLive(el, r, small);
    else if (ch.kind === "whatif") drawWhatIf(el, r, small);
    else if (ch.kind === "planner") drawPlannerCurve(el, r, small);
    else if (ch.kind === "leaderboard") {
      const n = r.names.length, ys = [...r.names].reverse(), xs = [...r.values].reverse(), ks = [...r.kinds].reverse();
      el.style.height = `${70 + 30 * n}px`;
      Plotly.react(el, [{ type: "bar", orientation: "h", y: ys, x: xs, marker: { color: ks.map((k) => (k === "timestral" ? C.orange : C.grey)) },
        hovertemplate: "%{y}: %{x:.4f}<extra></extra>" }], layout({ ...small, margin: { l: 8, r: 12, t: 10, b: 30 }, showlegend: false, hovermode: "closest", yaxis: { automargin: true, tickfont: { size: 10.5 } },
        xaxis: { title: { text: r.metric.toUpperCase(), font: { size: 12, color: C.muted } } } }), PCONF);
    } else box.remove();
  } catch (e) { console.error(e); box.remove(); }
}
async function sendChat() {
  const q = $("#chatIn").value.trim();
  if (!q || S.chat.busy) return;
  S.chat.busy = true; $("#chatSend").disabled = true; $("#chatIn").value = "";
  chatBubble("user", esc(q));
  const bot = chatBubble("bot", `<div class="status"><span class="spin"></span><span class="st">Thinking…</span></div><div class="ans"></div><div class="charts"></div>`);
  const ans = bot.querySelector(".ans"), st = bot.querySelector(".st"), charts = bot.querySelector(".charts");
  let text = "", agentLabel = "";
  const body = { message: q, history: S.chat.history, context: pageContext() };
  try {
    const res = await fetch("api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (res.status === 401) { location.reload(); return; }
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const raw = buf.slice(0, nl); buf = buf.slice(nl + 1);
        if (!raw.trim()) continue;
        const ev = JSON.parse(raw);
        if (ev.type === "text") { text += ev.text; ans.innerHTML = md(text); }
        else if (ev.type === "status") st.textContent = ev.text;
        else if (ev.type === "agent") agentLabel = `${ev.name}${ev.model ? ` · ${ev.model}` : ""}`;
        else if (ev.type === "reset") { text = ""; ans.innerHTML = ""; charts.innerHTML = ""; st.textContent = ev.text; }
        else if (ev.type === "chart") chatChart(charts, ev.chart);
        else if (ev.type === "error") ans.insertAdjacentHTML("beforeend", `<p class="err">⚠ ${esc(ev.text)}</p>`);
        else if (ev.type === "done") { bot.querySelector(".status")?.remove(); bot.insertAdjacentHTML("beforeend", `<div class="meta">${esc(agentLabel || "Answered")} · ${ev.seconds} s${ev.turns ? ` · ${ev.turns} steps` : ""}</div>`); }
        $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
      }
    }
  } catch (e) {
    ans.insertAdjacentHTML("beforeend", `<p class="err">⚠ ${esc(e.message)}</p>`);
  } finally {
    bot.querySelector(".status")?.remove();
    S.chat.history.push({ role: "user", text: q }, { role: "assistant", text });
    S.chat.busy = false; $("#chatSend").disabled = false; $("#chatIn").focus();
  }
}

// ================================================================== UPLOAD
function initUpload() {
  const drop = $("#drop"), inp = $("#upFile");
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); };
  inp.onchange = () => inp.files[0] && upload(inp.files[0]);
}
async function upload(file) {
  await withBusy($("#upCard"), async () => { const fd = new FormData(); fd.append("file", file); S.up = await api("api/upload", fd); renderUploadForm(S.up); });
}
function renderUploadForm(r) {
  const opts = (arr, sel, none) => (none ? `<option value="">${none}</option>` : "") + arr.map((c) => `<option ${c === sel ? "selected" : ""}>${esc(c)}</option>`).join("");
  const target0 = r.numeric.find((c) => !r.cat_guess.includes(c) && c !== r.id_guess) || r.numeric[0];
  $("#upForm").innerHTML = `
    <h3 style="margin:18px 0 4px">${esc(r.name)} <span class="note">· ${r.rows.toLocaleString("en-US")} rows · ${r.columns.length} columns</span></h3>
    <div class="scroll" style="max-height:220px;margin-bottom:14px"><table><thead><tr>${r.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
      <tbody>${r.preview.map((row) => `<tr>${row.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    <div class="form">
      <span class="lbl">Name</span><input type="text" id="upName" value="${esc(r.name.replace(/\.[^.]+$/, ""))}">
      <span class="lbl">Date column</span><select id="upDate">${opts(r.columns, r.date_guess)}</select>
      <span class="lbl">Series ID column</span><select id="upId">${opts(r.columns, r.id_guess, "— single series —")}</select>
      <span class="lbl">Forecast this</span><select id="upTarget">${opts(r.numeric, target0)}</select>
      <span class="lbl">Other columns</span><div class="roles" id="upRoles"></div>
      <span class="lbl">Frequency</span><select id="upFreq"><option value="auto">auto-detect</option><option value="h">hourly</option><option value="D">daily</option><option value="W">weekly</option><option value="MS">monthly</option><option value="QS">quarterly</option></select>
      <span class="lbl">Season / horizon</span><span><input type="number" id="upSeason" placeholder="auto"> cycle length &nbsp; <input type="number" id="upH" placeholder="auto"> steps ahead</span>
      <span class="lbl">Totals per period</span><select id="upAgg"><option value="sum">sum (sales, quantities, energy…)</option><option value="mean">average (prices, temperatures, rates…)</option></select>
      <span class="lbl">Calendar features</span><label><input type="checkbox" id="upCal" checked> add weekday / month / hour as known covariates</label>
      <span class="lbl">Public holidays</span><select id="upCountry"><option value="">none</option><option selected>IT</option><option>US</option><option>DE</option><option>FR</option><option>ES</option><option>GB</option><option>CH</option></select>
      <span></span><span><button class="primary" id="upGo">Load dataset</button> <span class="note">Season: 24 hourly · 7 daily · 52 weekly · 12 monthly</span></span>
    </div>`;
  const roles = () => {
    const skip = new Set([$("#upTarget").value, $("#upDate").value, $("#upId").value]);
    $("#upRoles").innerHTML = r.numeric.filter((c) => !skip.has(c)).map((c) => `<div class="r" data-c="${esc(c)}"><span title="${esc(c)}">${esc(c)}</span>
      <select class="role"><option value="">ignore</option><option value="past">past only</option><option value="known">known in advance</option></select>
      <label class="note"><input type="checkbox" class="cat" ${r.cat_guess.includes(c) ? "checked" : ""}> category</label></div>`).join("") || '<span class="note">no other numeric columns</span>';
  };
  roles();
  $("#upTarget").onchange = $("#upDate").onchange = $("#upId").onchange = roles;
  $("#upGo").onclick = registerUpload;
}
async function registerUpload() {
  const rs = $$("#upRoles .r");
  const body = { uid: S.up.uid, date_col: $("#upDate").value, target: $("#upTarget").value, id_col: $("#upId").value || null,
    past: rs.filter((x) => x.querySelector(".role").value === "past").map((x) => x.dataset.c),
    known: rs.filter((x) => x.querySelector(".role").value === "known").map((x) => x.dataset.c),
    cat: rs.filter((x) => x.querySelector(".cat").checked).map((x) => x.dataset.c),
    freq: $("#upFreq").value, season: +$("#upSeason").value || null, horizon: +$("#upH").value || null,
    calendar: $("#upCal").checked, country: $("#upCountry").value, name: $("#upName").value, agg: $("#upAgg").value };
  await withBusy($("#upCard"), async () => {
    const meta = await api("api/upload/register", body);
    S.datasets = await api("api/datasets");
    fillDatasets(meta.key);
    S.running = true;
    await onDatasetChange();
    showTab("overview");
  });
}

// ================================================================== ABOUT
async function renderAbout() {
  let sys = {};
  try { sys = await api("api/system"); } catch (e) { /* optional */ }
  const done = '<span class="tag done">in this demo</span>', next = '<span class="tag">next</span>';
  $("#aboutBody").innerHTML = `
  <h2>What is this?</h2>
  <p><b>Timestral</b> is an open time-series foundation model by Mistral AI. It forecasts any series <b>zero-shot</b> – no training on your data –
  and returns a full probability distribution (21 quantiles), not just one number. Everything here runs locally on the CPU: no GPU, no account,
  no API key, and your data never leaves this computer.</p>
  <h2>The tabs</h2>
  <ul>
    <li><b>Overview</b> – the analysis page: summary, headline numbers, leaderboard vs classic methods, error by step / weekday / group, calibration, best &amp; worst series.</li>
    <li><b>Series</b> – one series with holdout (orange), future (green) and the covariates underneath.</li>
    <li><b>Total</b> – the sum of all series: bottom-up vs forecasting the total directly.</li>
    <li><b>Explore backtest</b> – move “today” through history and watch the forecast adapt; later data is hidden.</li>
    <li><b>Live forecast</b> – forecast from any date and horizon on the spot.</li>
    <li><b>Split test</b> – give the model only part of the history (e.g. 2 of 5 years) and see how it forecasts the rest, period by period, against simple rules.</li>
    <li><b>What-if</b> – edit future covariates (promotions, opening days, weather…) and see the effect.</li>
    <li><b>Anomalies</b> – points outside the model’s uncertainty band.</li>
    <li><b>Order planner</b> – turn the forecast quantiles into how much to stock, and compare lost sales vs leftover stock (and their cost) with a classic “forecast + safety buffer”.</li>
    <li><b>💬 Ask about this page</b> (button at the bottom right, on every tab) – ask in plain English: Claude sees what is on screen,
      explains it, and can call the demo’s forecasting tools for more, with charts.</li>
    <li><b>Your data</b> – load a CSV with one or many series (e.g. all your stores).</li>
  </ul>
  <h2>How the evaluation works</h2>
  <p>For each series the last <i>horizon</i> points (several windows for single series) are hidden, forecast blind, and compared with reality.
  The same is done with classic baselines (repeat last week, same day last year, average by weekday × promotion, …).
  Results are computed once by a background pipeline and cached in <code>results/</code>, so the pages open instantly.</p>
  <h2>How to read the numbers</h2>
  <ul>
    <li><b>MAPE</b> – average % error per point (e.g. per store and day). <b>RMSPE</b> – the Kaggle Rossmann metric, punishes big misses.</li>
    <li><b>WAPE</b> – total absolute error / total volume: the business view. <b>sMAPE</b> – symmetric % error.</li>
    <li><b>MASE</b> – error relative to the “repeat last season” rule: <b>below 1 = better</b>.</li>
    <li><b>Bias</b> – positive = over-forecasting, negative = under-forecasting.</li>
    <li><b>WQL</b> – weighted quantile loss: scores the whole uncertainty band. <b>Cov. 80%</b> – share of real values inside the 10–90% band (≈80% = honest).
    <b>Width 80%</b> – how wide that band is relative to the volume.</li>
  </ul>
  <h2>Improvement ideas</h2>
  <ul>
    <li>Multi-series evaluation with leaderboard, error by step, per-series distribution and best/worst lists ${done}</li>
    <li>Covariates known in advance and the “closed days = missing” trick ${done}</li>
    <li>Bottom-up vs direct forecast of the total ${done}</li>
    <li>Backtest explorer, live forecast, what-if scenarios, anomaly detection ${done}</li>
    <li>From forecast to decision: order planner with service level and cost of lost sales vs leftovers ${done}</li>
    <li>Natural-language assistant that calls the forecasting tools (LLM + MCP) ${done}</li>
    <li>Rolling multi-origin evaluation for panels (more windows per store) and error by month ${next}</li>
    <li>Fine-tuning on company history to compare zero-shot vs adapted ${next}</li>
    <li>Scheduled forecasts exported to Excel / Power BI, with drift alerts ${next}</li>
    <li>Explanations: which covariates moved the forecast the most ${next}</li>
  </ul>
  <h2>Data &amp; licences</h2>
  <p>Model weights: “Modified MIT” – free, <b>but not for companies with consolidated revenue above 20 M$ per month</b> (~240 M$/year): above that a commercial
  licence from Mistral is required. Mistral API / Forge prices are not published.<br>
  Rossmann data: Kaggle competition dataset (2015), downloaded from a public GitHub mirror for this local demo – check Kaggle’s competition rules before any other use.</p>
  <h2>This machine</h2>
  <p class="note">${esc(sys.os || "")} · ${esc(sys.cpu || "")} · ${sys.cores || "?"} logical cores · Python ${esc(sys.python || "")} · torch ${esc(sys.torch || "")} (CPU only)</p>`;
}

boot().catch((e) => toast(e.message));
