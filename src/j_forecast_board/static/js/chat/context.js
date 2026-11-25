// SPDX-License-Identifier: Apache-2.0
import { sendChat } from "../chat/panel.js";
import { $, $$, esc } from "../core/dom.js";
import { ds, S, variantLabel } from "../core/state.js";

// The chat is a side panel available on every tab: each question carries what the user is looking at.
export const TAB_NAMES = { overview: "Overview", series: "Series", total: "Total", explore: "Explore backtest", live: "Live forecast",
  split: "Split test", whatif: "What-if", anomalies: "Anomalies", planner: "Order planner", upload: "Your data", about: "About" };
export const TAB_STATE = { overview: "ov", series: "se", total: "to", explore: "rp", live: "lv", split: "sp", whatif: "wi", anomalies: "ad", planner: "pl" };
export const CHAT_SUGGEST = {
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
export function chatContextLine() {
  if ($("#chatDrawer").hidden) return;
  const d = ds(), t = S.tab;
  $("#chatCtx").textContent = [TAB_NAMES[t] || t, d?.name, d && d.n > 1 ? `${d.id_label} #${d.ids[S.series]}` : null].filter(Boolean).join(" · ");
  const sug = ["Explain what this page shows.", ...(CHAT_SUGGEST[t] || [])];
  $("#chatSuggest").innerHTML = sug.map((q) => `<button type="button" class="sugg">${esc(q)}</button>`).join("");
  $$("#chatSuggest .sugg").forEach((b) => (b.onclick = () => { $("#chatIn").value = b.textContent; sendChat(); }));
}
/** Compact copy of a result object for the assistant: long series become min/max/mean/first/last. */
export function compact(v, depth = 0) {
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
export function pageContext() {
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
