// SPDX-License-Identifier: Apache-2.0
import { chatContextLine } from "./chat/context.js";
import { initChat } from "./chat/panel.js";
import { api } from "./core/api.js";
import { $, $$, esc } from "./core/dom.js";
import { dur, pct } from "./core/format.js";
import { common, ds, S, variant, variantLabel } from "./core/state.js";
import { toast } from "./core/ui.js";
import { renderAbout } from "./tabs/about.js";
import { initAnomalies, runAnomalies } from "./tabs/anomalies.js";
import { initExplore, runExplore, stopPlay } from "./tabs/explore.js";
import { initLive, runLive } from "./tabs/live.js";
import { renderRunbar, runOverview } from "./tabs/overview.js";
import { initPlanner, runPlanner } from "./tabs/planner.js";
import { initSeries, runSeries } from "./tabs/series.js";
import { initSplit, runSplit } from "./tabs/split.js";
import { runTotal } from "./tabs/total.js";
import { initUpload } from "./tabs/upload.js";
import { initWhatIf, runWhatIf } from "./tabs/whatif.js";

export async function boot() {
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
export function fillDatasets(sel) {
  $("#dsSel").innerHTML = S.datasets.map((d) => `<option value="${d.key}">${esc(d.name)}</option>`).join("");
  if (sel && S.datasets.some((d) => d.key === sel)) $("#dsSel").value = sel;
}
export async function onDatasetChange() {
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
export function setSeries(i) {
  S.series = i; $("#serSel").value = i;
  for (const t of ["series", "explore", "live", "split", "whatif", "anomalies", "planner"]) S.dirty[t] = true;
  S.wi = null; stopPlay(); refreshTab(); chatContextLine();
}
export function onVariantChange() {
  const o = $("#varSel").selectedOptions[0];
  if (o && o.dataset.done !== "1") {
    api("api/run", common({ variant: o.value })).then(() => refreshStatus(true)).catch((e) => toast(e.message));
  }
  S.chosen = variant();
  brand(); markAll();
}
export function brand() {
  // The model name, without the variant details ("· closed = missing"), but keeping "· stub".
  const parts = (variantLabel() || "Timestral").split(" · ");
  $("#brandModel").textContent = parts.filter((part, i) => i === 0 || part === "stub").join(" · ");
  $("#brandData").textContent = ds().name;
}
export function markAll() {
  for (const t of ["overview", "series", "total", "explore", "live", "split", "whatif", "anomalies", "planner"]) S.dirty[t] = true;
  stopPlay(); refreshTab();
}
export async function refreshStatus(force) {
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
export function showTab(t) {
  S.tab = t;
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${t}`));
  refreshTab();
  chatContextLine();
  window.dispatchEvent(new Event("resize"));
}
export function refreshTab() {
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
export function waitingFor(t) {
  S.dirty[t] = true;
  const msg = `<div class="empty">⏳ Timestral is evaluating <b>${esc(ds().name)}</b> in the background (first run only – results are cached on disk).<br>Progress is shown at the top right; this page updates by itself.</div>`;
  if (t === "overview") $("#ovOut").innerHTML = msg;
  if (t === "series") $("#seChips").innerHTML = msg;
  if (t === "total") $("#toChips").innerHTML = msg;
  if (t === "planner") $("#plChips").innerHTML = msg;
}
boot().catch((e) => toast(e.message));
