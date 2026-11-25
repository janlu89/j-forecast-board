// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { C, label, layout, line, PCONF, vline, vrect } from "../core/charts.js";
import { $, esc } from "../core/dom.js";
import { chip, dur, MET, mfmt, pct } from "../core/format.js";
import { common, ds, S } from "../core/state.js";
import { withBusy } from "../core/ui.js";

export function initExplore() {
  $("#rpRun").onclick = runExplore;
  $("#rpSlider").oninput = () => { stopPlay(); drawFrame(+$("#rpSlider").value); };
  $("#rpReveal").onchange = $("#rpFollow").onchange = () => S.rp && drawFrame(S.rpK);
  $("#rpPlay").onclick = () => (S.rpTimer ? stopPlay() : startPlay());
  $("#rpSpeed").onchange = () => { if (S.rpTimer) { stopPlay(); startPlay(); } };
}
export async function runExplore() {
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
export function drawFrame(k) {
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
export function drawReplayErrors() {
  const r = S.rp, P = r.meta.primary;
  Plotly.react("rpErr", [{ x: r.frames.map((f) => r.all[f.cut - 1]), y: r.frames.map((f) => f.err ?? null), type: "bar",
    marker: { color: r.frames.map((_, i) => (i === S.rpK ? C.orange : "#3a4155")) }, hovertemplate: `today %{x}<br>${MET[P][0]} %{y${P === "mase" ? ":.3f" : ":.2%"}}<extra></extra>` }],
  layout({ margin: { l: 64, r: 18, t: 8, b: 30 }, showlegend: false, hovermode: "closest", bargap: 0.25, yaxis: P === "mase" ? {} : { tickformat: ".0%" } }), { ...PCONF, displayModeBar: false });
  S.rpErrDrawn = true;
  const el = $("#rpErr"); el.removeAllListeners?.("plotly_click"); el.on("plotly_click", (ev) => { stopPlay(); drawFrame(ev.points[0].pointIndex); });
}
export function startPlay() {
  if (!S.rp) return;
  if (S.rpK >= S.rp.frames.length - 1) S.rpK = -1;
  $("#rpPlay").textContent = "❚❚";
  S.rpTimer = setInterval(() => { if (S.rpK >= S.rp.frames.length - 1) return stopPlay(); drawFrame(S.rpK + 1); }, +$("#rpSpeed").value);
}
export function stopPlay() { clearInterval(S.rpTimer); S.rpTimer = null; $("#rpPlay").textContent = "▶"; }
