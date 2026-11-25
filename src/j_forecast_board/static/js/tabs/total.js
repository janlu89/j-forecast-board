// SPDX-License-Identifier: Apache-2.0
import { api } from "../core/api.js";
import { band, C, label, layout, line, PCONF, unitAxis, vline, vrect } from "../core/charts.js";
import { $, esc } from "../core/dom.js";
import { chip, pct } from "../core/format.js";
import { common, ds, S } from "../core/state.js";
import { withBusy } from "../core/ui.js";
import { metricTable } from "../tabs/overview.js";

export async function runTotal() {
  if (ds().n < 2) return;
  await withBusy($("#toCard"), async () => { const r = await api("api/total", common()); S.to = r; renderTotal(r); });
}
export function renderTotal(r) {
  const T = r.dates.length, H = r.H, last = r.dates[T - 1], fd = r.future_dates;
  const tr = [line(r.dates, r.y, C.white, "actual total", { line: { width: 1.1 } })];
  const shapes = [vrect(r.dates[r.cuts[0]], last, C.orange, 0.07), vline(r.dates[r.cuts[0]], C.orange), vrect(last, fd.at(-1), C.green, 0.05), vline(last, C.green)];
  r.cuts.forEach((c, w) => {
    const x = r.dates.slice(c, c + H);
    if (r.direct) {
      tr.push(...band(x, r.direct.holdout[w].lo, r.direct.holdout[w].hi, C.purple, "direct 80%", 0.18, w === 0));
      tr.push(line(x, r.direct.holdout[w].median, C.purple, "direct (model on the total)", { line: { width: 1.4, dash: "dash" }, showlegend: w === 0 }));
    }
    if (r.bottom_up) tr.push(line(x, r.bottom_up.holdout[w], C.orange, "bottom-up (sum of series forecasts)", { line: { width: 2.2 }, showlegend: w === 0 }));
  });
  if (r.bottom_up) {
    const fx = [last, ...fd], j = (a) => [r.y[T - 1], ...a];
    if (r.direct) tr.push(...band(fx, j(r.direct.future.lo), j(r.direct.future.hi), C.purple, "direct 80% (future)", 0.14, false),
      line(fx, j(r.direct.future.median), C.purple, "direct", { line: { width: 1.4, dash: "dash" }, showlegend: false }));
    tr.push(line(fx, j(r.bottom_up.future), C.green, "bottom-up (future)", { line: { width: 2.2 } }));
  }
  const start = r.dates[Math.max(0, r.cuts[0] - 5 * H)];
  Plotly.react("toPlot", tr, layout({ shapes, annotations: [label(r.dates[r.cuts[0]], "holdout", C.orange), label(last, "future", C.green)],
    yaxis: unitAxis(`total ${r.meta.unit}`), margin: { l: 70, r: 18, t: 44, b: 10 },
    xaxis: { range: [start, fd.at(-1)], rangeslider: { visible: true, thickness: 0.08, bgcolor: "#0b0d12", bordercolor: "#232838", borderwidth: 1 } } }), PCONF);
  const best = r.table[0];
  $("#toChips").innerHTML = chip("Series summed", r.meta.n.toLocaleString("en-US")) + (best ? chip("Best on total", `${esc(best.name)} · MAPE ${pct(best.mape, 2)}`, "good") : "") +
    (r.model ? chip("Bottom-up model", esc(r.model)) : "");
  $("#toTable").innerHTML = metricTable(r.table, ["mape", "wape", "bias", "mae", "rmse", "coverage"], { first: true });
}
