// SPDX-License-Identifier: Apache-2.0
// Setting up the AI assistant: off until configured, tested, and (for external services) consented.
import { api } from "../core/api.js";
import { $, $$, esc } from "../core/dom.js";
import { S } from "../core/state.js";
import { toastOk } from "../core/ui.js";

const PRESETS = [
  { name: "Groq", url: "https://api.groq.com/openai/v1", keys: "https://console.groq.com/keys" },
  { name: "OpenRouter", url: "https://openrouter.ai/api/v1", keys: "https://openrouter.ai/settings/keys" },
  { name: "Mistral", url: "https://api.mistral.ai/v1", keys: "https://console.mistral.ai/api-keys" },
  { name: "OpenAI", url: "https://api.openai.com/v1", keys: "https://platform.openai.com/api-keys" },
];
const CONTEXT_LEVELS = [
  ["full", "The visible text and numbers, plus compact chart data"],
  ["numbers", "The visible text and numbers only"],
  ["none", "Only my question (the assistant can still call the forecasting tools)"],
];
// Speech, moderation and embedding models cannot chat: list them last.
const NON_CHAT = /whisper|tts|speech|audio|guard|embed|moderation|rerank|playai|transcri|dall-e|image|vision-only/i;

export function initAssistant() {
  $("#agentBtn").onclick = openSetup;
  $("#agentX").onclick = $("#agentCancel").onclick = () => $("#agentModal").close();
  $("#agentForm").onsubmit = (e) => { e.preventDefault(); useSelected(); };
  $("#agentOff").onclick = switchOff;
  return loadAssistant();
}

/** Refresh the assistant state and every place that shows it. */
export async function loadAssistant() {
  try { S.assistant = await api("api/assistant"); } catch (e) { return; }
  const a = activeAgent();
  const ready = S.assistant.ready;
  $("#chatFab").textContent = ready ? "💬 Ask about this page" : "💬 Set up the AI assistant";
  $("#agentName").textContent = a ? `${a.name}${a.model ? ` · ${a.model}` : ""}` : "Set up";
  $("#agentDot").className = `dot ${ready ? "ok" : "warn"}`;
  const badge = $("#egressBadge");
  badge.hidden = !(ready && a);
  if (ready && a) {
    badge.className = `egress ${a.egress}`;
    badge.textContent = a.egress === "local" ? "Local" : `External: ${a.destination}`;
    badge.title = a.egress === "local" ? "Questions and page contents stay on this PC."
      : `Questions and page contents are sent to ${a.destination}.`;
  }
  $("#chatIn").disabled = !ready;
  $("#chatSend").disabled = !ready;
  $("#chatIn").placeholder = ready ? "Ask about what you see, e.g. “Explain these numbers”" : S.assistant.reason;
}

const agentById = (id) => S.assistant.agents.find((x) => x.id === id);

export function activeAgent() {
  return S.assistant?.agents.find((x) => x.id === S.assistant.active) || null;
}

export function openSetup() {
  if (!S.assistant) return;
  const st = S.assistant, chosen = st.active || "local";
  $("#agentList").innerHTML = st.agents.map((a) => agentCard(a, a.id === chosen)).join("") + plannedCard();
  $("#agentContext").innerHTML = CONTEXT_LEVELS.map(([key, text]) =>
    `<label class="chk"><input type="radio" name="ctx" value="${key}" ${key === st.context_level ? "checked" : ""}> ${esc(text)}</label>`).join("");
  $$("#agentContext input").forEach((r) => (r.onchange = () => setContext(r.value)));
  wireCards();
  $("#agentOff").hidden = !st.active;
  $("#agentMsg").className = "note"; $("#agentMsg").textContent = st.ready ? "" : st.reason;
  $("#consentBox").hidden = true;
  $("#agentModal").showModal();
}

function agentCard(a, selected) {
  const fid = (f) => `ag_${a.id}_${f}`;
  const where = a.destination === "not set" ? "" : `<span class="egress ${a.egress}">${a.egress === "local" ? "Local" : `External: ${esc(a.destination)}`}</span>`;
  const state = a.blocked ? `<span class="tag bad">blocked</span>` : a.tested ? `<span class="tag done">tested</span>` : "";
  let fields = "";
  if (a.needs_url) {
    const presets = a.id === "api" ? `<div class="presets">${PRESETS.map((p) =>
      `<button type="button" data-preset="${esc(p.url)}" data-keys="${esc(p.keys)}">${esc(p.name)}</button>`).join("")}</div>` : "";
    const detect = a.id === "local" ? `<button type="button" data-detect>Find a server on this PC</button><span class="note" data-found></span>` : "";
    fields += `${presets}<label class="fld"><span>Base URL</span><input type="text" id="${fid("base_url")}" data-f="base_url"
      value="${esc(a.base_url || a.default_url || "")}" placeholder="https://…/v1" spellcheck="false" autocomplete="off"></label>${detect}`;
  }
  if (a.models.length) {
    fields += `<label class="fld"><span>Model</span><select id="${fid("model")}" data-f="model">${a.models.map((m) =>
      `<option ${m === a.model ? "selected" : ""}>${esc(m)}</option>`).join("")}</select></label>`;
  } else {
    fields += `<div class="fld"><label for="${fid("model")}">Model</label><div class="modelrow">
      <select id="${fid("model")}" data-f="model">${modelOptions(a.model ? [a.model] : [], a.model)}</select></div></div>
      <label class="fld manual" hidden><span>Model id</span><input type="text" data-f="model_manual" placeholder="type the model id" spellcheck="false" autocomplete="off"></label>`;
  }
  if (a.needs_key) {
    const hint = a.has_key ? `saved (${a.key_hint}): leave empty to keep it` : "paste the API key";
    fields += `<label class="fld"><span>API key <a data-keylink target="_blank" rel="noopener" hidden>get one</a></span>
      <input type="password" data-f="api_key" placeholder="${esc(hint)}" autocomplete="new-password"></label>`;
  }
  if (a.needs_cli) fields += `<p class="note">Needs <code>${esc(a.needs_cli)}</code> installed and signed in on this PC.</p>`;
  return `<div class="agentcard ${selected ? "sel" : ""}" data-id="${a.id}">
    <label class="agenthd"><input type="radio" name="agent" value="${a.id}" ${selected ? "checked" : ""} ${a.blocked ? "disabled" : ""}>
      <span><b>${esc(a.name)}</b> <span class="note">· ${esc(a.vendor)}</span> ${where} ${state}
      ${a.id === S.assistant.active ? '<span class="tag done">in use</span>' : ""}</span></label>
    <div class="note">${esc(a.help)}</div>
    ${a.blocked ? `<p class="note errc">${esc(a.blocked)}</p>` : ""}
    <div class="agentbody">${fields}
      <div class="agenttest"><button type="button" data-test>Save and test</button><span class="note" data-res></span></div>
    </div></div>`;
}

function plannedCard() {
  return `<div class="agentcard planned"><div class="agenthd"><span><b>GitHub Copilot CLI</b> <span class="note">· GitHub</span>
    <span class="tag">planned</span></span></div><div class="note">Not available yet: it ships once it can be limited to this
    app's tools only (no shell, no files). See the README.</div></div>`;
}

function modelOptions(models, current) {
  const chat = models.filter((m) => !NON_CHAT.test(m)), other = models.filter((m) => NON_CHAT.test(m));
  const opt = (m) => `<option value="${esc(m)}" ${m === current ? "selected" : ""}>${esc(m)}</option>`;
  const head = `<option value="" ${current ? "" : "selected"}>${models.length ? "— choose a model —" : "— press Save and test —"}</option>`;
  return head + chat.map(opt).join("") + (other.length ? `<optgroup label="Probably not for chat">${other.map(opt).join("")}</optgroup>` : "")
    + `<option value="__manual__">✎ Type a model id…</option>`;
}

function wireCards() {
  const select = (id) => $$("#agentList .agentcard").forEach((c) => c.classList.toggle("sel", c.dataset.id === id));
  $$("#agentList input[name=agent]").forEach((r) => (r.onchange = () => select(r.value)));
  $$("#agentList .agentcard:not(.planned)").forEach((card) => {
    const id = card.dataset.id;
    card.onfocusin = () => { const r = card.querySelector("input[name=agent]"); if (r && !r.checked && !r.disabled) { r.checked = true; select(id); } };
    card.querySelector("[data-test]").onclick = () => saveAndTest(id);
    card.querySelectorAll("[data-preset]").forEach((b) => (b.onclick = () => {
      card.querySelector("[data-f=base_url]").value = b.dataset.preset;
      const link = card.querySelector("[data-keylink]");
      if (link) { link.href = b.dataset.keys; link.hidden = false; }
      card.querySelector("[data-f=api_key]")?.focus();
    }));
    const detect = card.querySelector("[data-detect]");
    if (detect) detect.onclick = () => findLocal(card);
    const model = card.querySelector("select[data-f=model]");
    model.onchange = () => {
      const manual = card.querySelector(".fld.manual");
      if (manual) { manual.hidden = model.value !== "__manual__"; if (!manual.hidden) manual.querySelector("input").focus(); }
    };
  });
}

function readCard(id) {
  const card = $(`#agentList .agentcard[data-id="${id}"]`), out = {};
  card.querySelectorAll("[data-f]").forEach((el) => { out[el.dataset.f] = el.value.trim(); });
  if (out.model === "__manual__") out.model = out.model_manual || "";
  delete out.model_manual;
  if (!out.api_key) delete out.api_key;
  return out;
}

async function saveAndTest(id) {
  const card = $(`#agentList .agentcard[data-id="${id}"]`), res = card.querySelector("[data-res]"), btn = card.querySelector("[data-test]");
  res.className = "note"; res.textContent = "Saving and connecting…"; btn.disabled = true;
  try {
    const values = readCard(id);
    await api(`api/assistant/agents/${id}`, values);
    const r = await api(`api/assistant/agents/${id}/test`, {});
    res.className = `note ${r.ok ? "okc" : "errc"}`; res.textContent = r.message;
    const sel = card.querySelector("select[data-f=model]");
    if (r.models?.length && !agentById(id).models.length) {  // APIs list their models; keep a typed id too
      const list = values.model && !r.models.includes(values.model) ? [values.model, ...r.models] : r.models;
      sel.innerHTML = modelOptions(list, values.model);
    }
    if (r.ok && !values.model && sel.options.length > 1) {
      res.textContent = `${r.message} Now choose the model, then press Save and test again.`; sel.focus();
    }
    await loadAssistant();
    refreshCardBadges(id);
  } catch (e) { res.className = "note errc"; res.textContent = e.message; } finally { btn.disabled = false; }
}

function refreshCardBadges(id) {
  const a = S.assistant.agents.find((x) => x.id === id), card = $(`#agentList .agentcard[data-id="${id}"]`);
  const head = card.querySelector(".agenthd span");
  head.querySelectorAll(".egress, .tag").forEach((n) => n.remove());
  if (a.destination !== "not set") head.insertAdjacentHTML("beforeend",
    ` <span class="egress ${a.egress}">${a.egress === "local" ? "Local" : `External: ${esc(a.destination)}`}</span>`);
  if (a.tested) head.insertAdjacentHTML("beforeend", ' <span class="tag done">tested</span>');
}

async function findLocal(card) {
  const out = card.querySelector("[data-found]");
  out.textContent = "Looking on the usual ports…";
  try {
    const { servers } = await api("api/assistant/detect-local", {});
    if (!servers.length) { out.textContent = "No server found. Start one (llama.cpp, Ollama, LM Studio), then try again."; return; }
    out.innerHTML = servers.map((s, i) => `<button type="button" data-pick="${i}">${esc(s.name)}</button>`).join(" ");
    out.querySelectorAll("[data-pick]").forEach((b) => (b.onclick = () => {
      const s = servers[+b.dataset.pick];
      card.querySelector("[data-f=base_url]").value = s.base_url;
      card.querySelector("select[data-f=model]").innerHTML = modelOptions(s.models, s.models[0] || "");
    }));
  } catch (e) { out.textContent = e.message; }
}

async function useSelected() {
  const id = $("#agentList input[name=agent]:checked")?.value;
  if (!id) return;
  const a = S.assistant.agents.find((x) => x.id === id);
  if (!a.tested) { message(`Press “Save and test” for ${a.name} first, and make sure the test passes.`, true); return; }
  if (a.egress === "external" && !a.consent) { askConsent(a); return; }
  await activate(id, false, false);
}

function askConsent(a) {
  const box = $("#consentBox");
  $("#consentDest").textContent = a.destination;
  $("#consentPrivate").hidden = !S.assistant.policy.allow_private_data_to_external_ai;
  $("#consentOk").checked = false; $("#consentPrivateOk").checked = false;
  $("#consentGo").disabled = true;
  $("#consentOk").onchange = () => ($("#consentGo").disabled = !$("#consentOk").checked);
  $("#consentGo").onclick = () => activate(a.id, true, $("#consentPrivateOk").checked);
  $("#consentBack").onclick = () => (box.hidden = true);
  box.hidden = false;
  $("#consentOk").focus();
}

async function activate(id, consent, privateData) {
  try {
    S.assistant = await api("api/assistant/activate", { id, consent, private_data: privateData });
    await loadAssistant();
    $("#agentModal").close();
    const a = activeAgent();
    toastOk(`Assistant: ${a.name}${a.model ? ` · ${a.model}` : ""} (${a.egress === "local" ? "stays on this PC" : `sends to ${a.destination}`})`);
  } catch (e) { message(e.message, true); }
}

async function switchOff() {
  try { await api("api/assistant/deactivate", {}); await loadAssistant(); $("#agentModal").close(); toastOk("Assistant switched off."); }
  catch (e) { message(e.message, true); }
}

async function setContext(level) {
  try { S.assistant = await api("api/assistant/context", { level }); } catch (e) { message(e.message, true); }
}

function message(text, error) {
  $("#agentMsg").className = `note ${error ? "errc" : ""}`;
  $("#agentMsg").textContent = text;
}
