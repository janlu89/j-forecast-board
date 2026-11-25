// SPDX-License-Identifier: Apache-2.0

export async function api(path, body) {
  const opt = body instanceof FormData ? { method: "POST", body }
    : body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {};
  const res = await fetch(path, opt);
  if (res.status === 401) { location.reload(); throw new Error("Session expired: please sign in again."); }
  const js = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok || js.error) throw new Error(js.error || res.statusText);
  return js;
}
