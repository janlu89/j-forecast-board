# SPDX-License-Identifier: Apache-2.0
"""Order planner: turn the forecast's quantiles into a stocking decision and score it on the
holdout.

Everything is computed from the cached backtest (no new model run), so it is instant.
  * Timestral: order = forecast quantile at the chosen level (e.g. P90).
  * Classic practice: order = best simple rule x safety buffer (e.g. +20%).
The two are compared at the same availability (fill rate), and on cost.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ...domain.errors import InvalidRequest, NotReady
from ...domain.forecast import quantile_index
from ...domain.planning import BUFFERS, check_costs, critical_ratio, score_orders, value_at_fill
from ...domain.series import PERIOD_NAME
from ..view_model import Date, Dates, Numbers, clean, dataset_meta, number
from ..workbench import Scope, Workbench

LOWEST_ORDER_LEVEL = 0.3
BASELINE_CURVE_STEP = 3  # every third buffer is enough to draw the curve


@dataclass(frozen=True)
class PlanRequest:
    series: int = 0
    scope: str = "all"  # all | series
    margin: float = 0.4  # margin lost on a missed sale, share of the value
    holding: float = 0.15  # cost of a leftover unit (holding, markdown, waste), share of the value
    target: float = 0.95  # availability (fill rate) to compare the two approaches at


class OrderPlanner:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(self, scope: Scope, variant_key: str, request: PlanRequest) -> dict:
        check_costs(request.margin, request.holding, request.target)
        ds, horizon = scope.ds, scope.horizon
        panel = self._workbench.evaluations.panel(ds, horizon, scope.context)
        if not panel.model_rows:
            raise NotReady(
                "No Timestral results yet for this dataset: wait for the background evaluation."
            )
        row = next((r for r in panel.model_rows if r["key"] == variant_key), panel.model_rows[0])
        levels = row["levels"]
        primary = ds.primary
        best_baseline = min(panel.baseline_rows, key=lambda r: panel.score(r).get(primary) or 1e9)

        whole = request.scope == "all" or ds.N == 1
        selection = slice(None) if whole else slice(request.series, request.series + 1)
        mask = panel.M[selection]
        demand = panel.A[selection][mask]
        if demand.size == 0:
            raise InvalidRequest("No scored points for this selection.")
        if np.nanmin(demand) < 0:
            raise InvalidRequest("The order planner needs demand-like data (no negative values).")
        quantiles = row["Q"][selection][mask]  # (points, levels)
        classic = np.maximum(best_baseline["P"][selection][mask], 0.0)
        margin, holding = request.margin, request.holding

        model_curve = [
            dict(
                level=lv,
                **score_orders(demand, quantiles[:, quantile_index(lv, levels)], margin, holding),
            )
            for lv in levels
            if lv >= LOWEST_ORDER_LEVEL
        ]
        baseline_curve = [
            dict(buffer=float(k), **score_orders(demand, classic * k, margin, holding))
            for k in BUFFERS
        ]

        # 1) same availability: how much leftover stock does each approach need?
        same = dict(
            target=request.target,
            timestral=value_at_fill(model_curve, request.target, "leftover_pct"),
            baseline=value_at_fill(baseline_curve, request.target, "leftover_pct"),
            timestral_level=value_at_fill(model_curve, request.target, "level"),
            baseline_buffer=value_at_fill(baseline_curve, request.target, "buffer"),
        )
        if same["timestral"] is not None and same["baseline"]:
            same["saving"] = 1 - same["timestral"] / same["baseline"]

        # 2) cost: the model at the textbook quantile (no tuning) vs the classic rule with its
        # best buffer in hindsight
        ratio = critical_ratio(margin, holding)
        order_level = levels[quantile_index(ratio, levels)]
        model_best = dict(
            name=f"Timestral · order P{round(order_level * 100)} (critical ratio {ratio:.0%})",
            kind="timestral",
            **score_orders(
                demand, quantiles[:, quantile_index(order_level, levels)], margin, holding
            ),
        )
        model_median = dict(
            name="Timestral · order the median (no buffer)",
            kind="timestral",
            **score_orders(demand, quantiles[:, quantile_index(0.5, levels)], margin, holding),
        )
        tuned = min(baseline_curve, key=lambda c: c["cost"])
        baseline_best = dict(
            name=f"{best_baseline['name']} × {tuned['buffer']:.2f}"
            " (best buffer, tuned in hindsight)",
            kind="baseline",
            **{k: tuned[k] for k in tuned if k != "buffer"},
        )
        baseline_raw = dict(
            name=f"{best_baseline['name']} (no buffer)",
            kind="baseline",
            **score_orders(demand, classic, margin, holding),
        )
        table = sorted(
            [model_best, model_median, baseline_best, baseline_raw], key=lambda r: r["cost"]
        )
        periods = panel.A.shape[1] * panel.A.shape[2]  # windows x horizon steps scored per series
        cost = dict(
            ratio=ratio,
            level=order_level,
            timestral=model_best["cost"],
            baseline=baseline_best["cost"],
            saving=baseline_best["cost"] - model_best["cost"],
            saving_pct=1 - model_best["cost"] / baseline_best["cost"]
            if baseline_best["cost"]
            else None,
            per_year=ds.steps_per_year / periods,
            demand=float(demand.sum()),
        )

        return dict(
            meta=dataset_meta(ds),
            model=row["name"],
            baseline=best_baseline["name"],
            scope="all" if whole else "series",
            id=ds.ids[request.series],
            points=int(demand.size),
            period=PERIOD_NAME.get(ds.freq, "period"),
            margin=margin,
            holding=holding,
            windows=[dict(start=Date(ds, c), end=Date(ds, c + horizon - 1)) for c in panel.cuts],
            timestral_curve=[clean(c) for c in model_curve],
            baseline_curve=[clean(c) for c in baseline_curve[::BASELINE_CURVE_STEP]],
            same=clean(same),
            cost=clean(cost),
            table=[clean(r) for r in table],
            plan=self._next_orders(ds, row, request.series, horizon, order_level),
        )

    @staticmethod
    def _next_orders(ds, row: dict, s: int, horizon: int, order_level: float) -> dict:
        """What to order for the next period of the selected series."""
        future = row["res"].fut[s]
        levels = row["levels"]
        shown = min(ds.T, max(3 * horizon, 4 * ds.season))

        def at(level):
            return future[:, quantile_index(level, levels)]

        return dict(
            id=ds.ids[s],
            dates=Dates(ds, range(ds.T - shown, ds.T)),
            y=Numbers(ds.y_display(s)[-shown:], 2),
            future_dates=Dates(ds, range(ds.T, ds.T + horizon)),
            median=Numbers(at(0.5), 2),
            order=Numbers(at(order_level), 2),
            lo=Numbers(at(0.1), 2),
            hi=Numbers(at(0.9), 2),
            total_median=number(float(np.nansum(at(0.5))), 1),
            total_order=number(float(np.nansum(at(order_level))), 1),
        )
