# SPDX-License-Identifier: Apache-2.0
"""The total of all series: sum of the per-series forecasts (bottom-up) vs forecasting the total
directly."""

from __future__ import annotations

import numpy as np

from ...domain.errors import InvalidRequest
from ...domain.forecast import ModelVariant, quantile_index
from ...domain.metrics import metrics
from ..view_model import Dates, Numbers, clean, dataset_meta
from ..workbench import Scope, Workbench
from .overview import MAX_ERROR

DIGITS = 1


class TotalView:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(self, scope: Scope) -> dict:
        ds, horizon = scope.ds, scope.horizon
        if ds.N < 2:
            raise InvalidRequest(
                "This dataset has a single series: there is no total to aggregate."
            )
        panel = self._workbench.evaluations.panel(ds, horizon, scope.context)
        total = ds.total()
        actual = np.stack([total[c : c + horizon] for c in panel.cuts])
        mask = np.isfinite(actual) & (actual > 0)
        out = dict(
            meta=dataset_meta(ds),
            H=horizon,
            dates=Dates(ds, range(ds.T)),
            y=Numbers(total, DIGITS),
            future_dates=Dates(ds, range(ds.T, ds.T + horizon)),
            cuts=[int(c) for c in panel.cuts],
            lines=[],
            table=[],
        )
        for row in panel.rows:
            scores = metrics(actual, row["P"].sum(axis=0), mask)
            out["table"].append(
                dict(name=f"{row['name']} · bottom-up", kind=row["kind"], **clean(scores))
            )
        for row in panel.model_rows:
            result = row["res"]
            if result.total_bt is None:
                continue
            median = result.total_bt[..., quantile_index(0.5, result.levels)]
            scores = metrics(actual, median, mask, quantiles=result.total_bt, levels=result.levels)
            repo = ModelVariant.parse(row["key"]).repo
            name = f"{self._workbench.model.display_name(repo)} · direct on total"
            if not any(t["name"] == name for t in out["table"]):
                out["table"].append(dict(name=name, kind="direct", **clean(scores)))
        out["table"].sort(key=lambda x: x.get("mape") if x.get("mape") is not None else MAX_ERROR)
        best_name = next((t["name"] for t in out["table"] if t["kind"] == "timestral"), None)
        best = next((r for r in panel.model_rows if f"{r['name']} · bottom-up" == best_name), None)
        if best is not None:
            out.update(self._lines(best, panel))
        return out

    @staticmethod
    def _lines(best: dict, panel) -> dict:
        result = best["res"]
        levels = result.levels

        def at(values, level):
            return Numbers(values[..., quantile_index(level, levels)], DIGITS)

        out = dict(
            model=best["name"],
            bottom_up=dict(
                holdout=[Numbers(best["P"].sum(axis=0)[w], DIGITS) for w in range(len(panel.cuts))],
                future=Numbers(at(result.fut, 0.5).values.sum(axis=0), DIGITS),
            ),
        )
        if result.total_bt is not None:
            out["direct"] = dict(
                holdout=[
                    dict(
                        median=at(result.total_bt[w], 0.5),
                        lo=at(result.total_bt[w], 0.1),
                        hi=at(result.total_bt[w], 0.9),
                    )
                    for w in range(len(panel.cuts))
                ],
                future=dict(
                    median=at(result.total_fut, 0.5),
                    lo=at(result.total_fut, 0.1),
                    hi=at(result.total_fut, 0.9),
                ),
            )
        return out
