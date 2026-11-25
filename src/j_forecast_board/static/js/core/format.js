// SPDX-License-Identifier: Apache-2.0

export function fmt(v, d = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const a = Math.abs(v);
  if (a >= 10000) return v.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (a >= 100) return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
  return v.toLocaleString("en-US", { maximumFractionDigits: d });
}
export const pct = (v, d = 1) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)}%`);
export const spct = (v, d = 1) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%`);
export const dur = (s) => (s === null || s === undefined ? "–" : s < 90 ? `${s.toFixed(s < 10 ? 1 : 0)} s` : `${(s / 60).toFixed(1)} min`);
export const ms = (s) => Date.parse(String(s).length > 10 ? String(s).replace(" ", "T") : s + "T00:00");
export const chip = (label, value, cls = "") => `<span class="chip ${cls}">${label} <b>${value}</b></span>`;
export const MET = {
  mape: ["MAPE", (v) => pct(v, 2), "mean absolute % error"], rmspe: ["RMSPE", (v) => pct(v, 2), "Kaggle metric"],
  wape: ["WAPE", (v) => pct(v, 2), "total error / total volume"], smape: ["sMAPE", (v) => pct(v, 2)],
  mase: ["MASE", (v) => fmt(v, 3), "< 1 beats the seasonal naive"], bias: ["Bias", (v) => spct(v, 2), "+ = over-forecast"],
  mae: ["MAE", (v) => fmt(v)], rmse: ["RMSE", (v) => fmt(v)], wql: ["WQL", (v) => pct(v, 2), "quantile loss"],
  coverage: ["Cov. 80%", (v) => pct(v, 1), "target 80%"], width: ["Width 80%", (v) => pct(v, 1), "band width / volume"],
  secs: ["Time", (v) => dur(v)],
};
export const mfmt = (k, v) => (MET[k] ? MET[k][1](v) : fmt(v));

/** One CSV cell: text that a spreadsheet would run as a formula gets a leading quote (numbers are left alone). */
export function csvCell(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return /^[=+\-@\t\r]/.test(text) && Number.isNaN(Number(text)) ? `'${text}` : text;
}
