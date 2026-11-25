// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { $, $$, esc } from "../core/dom.js";
import { ds, S } from "../core/state.js";
import { toastOk, withBusy } from "../core/ui.js";
import { fillDatasets, onDatasetChange, showTab } from "../main.js";

export function initUpload() {
  const drop = $("#drop"), inp = $("#upFile");
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); };
  inp.onchange = () => inp.files[0] && upload(inp.files[0]);
  renderUploads();
}
export async function upload(file) {
  await withBusy($("#upCard"), async () => { const fd = new FormData(); fd.append("file", file); S.up = await api("api/upload", fd); renderUploadForm(S.up); });
}
export function renderUploadForm(r) {
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
export async function registerUpload() {
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
    renderUploads();
    showTab("overview");
  });
}

/** The user's own datasets: where they live, and a way to delete each one. */
export function renderUploads() {
  const mine = S.datasets.filter((d) => d.visibility === "private");
  if (!mine.length) { $("#upList").innerHTML = ""; return; }
  $("#upList").innerHTML = `<div class="card"><h3>Your datasets</h3>
    <div class="sub">They live only in this app's memory: they are gone when the app stops, and they are never sent to an external AI assistant.</div>
    ${mine.map((d) => `<div class="uprow"><span><b>${esc(d.name)}</b> <span class="note">· ${d.n} series × ${d.points} steps</span></span>
      <button type="button" data-delete="${esc(d.key)}">Delete this dataset</button></div>`).join("")}</div>`;
  $$("#upList [data-delete]").forEach((b) => (b.onclick = () => deleteUpload(b.dataset.delete)));
}

async function deleteUpload(key) {
  await withBusy($("#upList"), async () => {
    await api(`api/datasets/${encodeURIComponent(key)}/delete`, {});
    S.datasets = await api("api/datasets");
    if (ds()?.key === key || !ds()) { fillDatasets(S.datasets[0]?.key); await onDatasetChange(); }
    renderUploads();
    toastOk("Dataset deleted, with everything computed from it.");
  });
}
