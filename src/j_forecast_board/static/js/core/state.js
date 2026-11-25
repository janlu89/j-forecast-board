// SPDX-License-Identifier: Apache-2.0
import { $ } from "../core/dom.js";

export const S = { datasets: [], dirty: {}, tab: "overview", series: 0 };
export const ds = () => S.datasets.find((d) => d.key === $("#dsSel").value);
export const variant = () => $("#varSel").value;
export const variantLabel = () => $("#varSel").selectedOptions[0]?.dataset.label || "";
export function common(extra = {}) {
  const ctx = $("#context").value;
  return { dataset: $("#dsSel").value, horizon: +$("#horizon").value || null, context: ctx === "" ? null : +ctx,
    series: S.series, variant: variant(), ...extra };
}
