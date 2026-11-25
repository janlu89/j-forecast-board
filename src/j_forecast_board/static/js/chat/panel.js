// SPDX-License-Identifier: Apache-2.0
import { initAssistant, loadAssistant, openSetup } from "../chat/setup.js";
import { chatContextLine, pageContext } from "../chat/context.js";
import { md } from "../chat/markdown.js";
import { C, layout, PCONF } from "../core/charts.js";
import { $, esc } from "../core/dom.js";
import { S } from "../core/state.js";
import { drawLive } from "../tabs/live.js";
import { drawPlannerCurve } from "../tabs/planner.js";
import { drawWhatIf } from "../tabs/whatif.js";

export function initChat() {
  S.chat = { history: [], busy: false };
  $("#chatFab").onclick = () => { toggleChat(true); if (!S.assistant?.ready) openSetup(); };
  $("#chatClose").onclick = () => toggleChat(false);
  $("#chatForm").onsubmit = (e) => { e.preventDefault(); sendChat(); };
  $("#chatIn").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } };
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#chatDrawer").hidden && !$("#agentModal").open) toggleChat(false); });
  initAssistant();
}
export function toggleChat(open) {
  $("#chatDrawer").hidden = !open;
  $("#chatFab").hidden = open;
  $("#chatFab").setAttribute("aria-expanded", String(open));
  document.body.classList.toggle("chat-open", open);
  if (open) { chatContextLine(); $("#chatIn").focus(); }
  window.dispatchEvent(new Event("resize"));  // charts reflow to the narrower page
}
export function chatBubble(role, html = "") {
  const d = document.createElement("div");
  d.className = `msg ${role}`; d.innerHTML = html;
  $("#chatLog").appendChild(d); $("#chatLog").scrollTop = $("#chatLog").scrollHeight;
  return d;
}
export function chatChart(host, ch) {
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
export async function sendChat() {
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
    if (!res.ok || !res.body) {
      const problem = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      if (res.status === 409) {  // not set up, or consent missing: offer the setup
        ans.innerHTML = `<p class="err">⚠ ${esc(problem.error)}</p><button type="button" class="primary" data-setup>Set up the assistant</button>`;
        ans.querySelector("[data-setup]").onclick = openSetup;
        loadAssistant();
        return;
      }
      throw new Error(problem.error || `HTTP ${res.status}`);
    }
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
        else if (ev.type === "agent") agentLabel = `${ev.name}${ev.model ? ` · ${ev.model}` : ""} · ${ev.egress === "local" ? "on this PC" : `sent to ${ev.destination}`}`;
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
