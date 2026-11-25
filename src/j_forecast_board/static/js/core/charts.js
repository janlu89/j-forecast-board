// SPDX-License-Identifier: Apache-2.0

export const C = { white: "#e6e8ee", muted: "#8a90a2", orange: "#ff7a1a", green: "#34d399", blue: "#60a5fa",
  purple: "#a78bfa", red: "#f87171", grey: "#6b7280", grid: "#1f2431", line: "#2a3040", yellow: "#fbbf24" };
export const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
export const T_COLORS = [C.orange, C.yellow, "#f472b6", "#22d3ee", "#fb923c", "#e879f9"];
export const B_COLORS = ["#9ca3af", "#818cf8", "#6b7280", "#94a3b8"];
export const PCONF = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] };
export function layout(extra = {}) {
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
export function band(x, lo, hi, color, name, a = 0.22, legend = true) {
  return [
    { x, y: lo, type: "scatter", mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
    { x, y: hi, type: "scatter", mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: rgba(color, a), name, hoverinfo: "skip", showlegend: legend },
  ];
}
export const line = (x, y, color, name, extra = {}) => ({ x, y, type: "scatter", mode: "lines", name, hovertemplate: "%{y:,.2f}", ...extra,
  line: { color, width: 1.6, ...(extra.line || {}) } });
export const vline = (x, color, dash = "dash") => ({ type: "line", x0: x, x1: x, yref: "paper", y0: 0, y1: 1, line: { color, width: 1.2, dash } });
export const vrect = (x0, x1, color, a) => ({ type: "rect", x0, x1, yref: "paper", y0: 0, y1: 1, fillcolor: rgba(color, a), line: { width: 0 }, layer: "below" });
export const label = (x, text, color) => ({ x, y: 1, yref: "paper", text, showarrow: false, xanchor: "left", yanchor: "top", font: { color, size: 11 }, xshift: 4 });
export const unitAxis = (u) => ({ title: { text: u, font: { size: 12, color: C.muted } } });
