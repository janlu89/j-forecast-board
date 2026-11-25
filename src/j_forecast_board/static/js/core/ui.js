// SPDX-License-Identifier: Apache-2.0
import { $ } from "../core/dom.js";

export function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(toast.h); toast.h = setTimeout(() => (t.style.display = "none"), 9000);
}
export async function withBusy(el, fn) {
  el.classList.add("busy");
  try { return await fn(); } catch (e) { toast(e.message); console.error(e); } finally { el.classList.remove("busy"); }
}
export function toastOk(msg) { toast(msg); $("#toast").classList.add("ok"); setTimeout(() => $("#toast").classList.remove("ok"), 9000); }
