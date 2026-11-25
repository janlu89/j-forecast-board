# SPDX-License-Identifier: Apache-2.0
"""One series: history, holdout forecasts, future forecast, its scores and covariates; and the
ranking."""

from __future__ import annotations

import numpy as np

from ...domain.calendar import known_extended
from ...domain.forecast import quantile_index
from ..view_model import Dates, Numbers, clean, dataset_meta, number
from ..workbench import Scope, Workbench
from .overview import MAX_ERROR

DIGITS = 3


def _band(quantiles: np.ndarray, levels, wide: bool = False) -> dict:
    def at(level):
        return Numbers(quantiles[..., quantile_index(level, levels)], DIGITS)

    band = dict(median=at(0.5), lo=at(0.1), hi=at(0.9))
    if wide:
        band.update(lo90=at(0.05), hi90=at(0.95))
    return band


class SeriesView:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(self, scope: Scope, series: int, variant_key: str) -> dict:
        ds, horizon = scope.ds, scope.horizon
        s = self._workbench.series(ds, series)
        panel = self._workbench.evaluations.panel(ds, horizon, scope.context)
        primary = ds.primary
        row = panel.row_for(variant_key)
        baseline_errors = {r["key"]: panel.score(r).get(primary) for r in panel.baseline_rows}
        best_baseline = min(
            panel.baseline_rows,
            key=lambda r: (
                baseline_errors[r["key"]] if baseline_errors[r["key"]] is not None else MAX_ERROR
            ),
        )
        out = dict(
            meta=dataset_meta(ds),
            index=s,
            id=ds.ids[s],
            H=horizon,
            primary=primary,
            dates=Dates(ds, range(ds.T)),
            y=Numbers(ds.y_display(s), DIGITS),
            future_dates=Dates(ds, range(ds.T, ds.T + horizon)),
            attrs={k: _plain(values[s]) for k, values in ds.attrs.items()},
            cuts=[int(c) for c in panel.cuts],
            baseline=dict(
                name=best_baseline["name"],
                values=[Numbers(best_baseline["P"][s, w], DIGITS) for w in range(len(panel.cuts))],
            ),
        )
        if row is not None:
            result = row["res"]
            out["model"] = row["name"]
            out["variant"] = row["key"]
            out["holdout"] = [_band(result.bt[s, w], result.levels) for w in range(len(panel.cuts))]
            out["future"] = _band(result.fut[s], result.levels, wide=True)
        table = []
        for scored in panel.rows:
            scores = panel.score(scored, s)
            if scores:
                table.append(
                    dict(
                        name=scored["name"], kind=scored["kind"], key=scored["key"], **clean(scores)
                    )
                )
        table.sort(key=lambda x: x.get(primary) if x.get(primary) is not None else MAX_ERROR)
        out["table"] = table
        out["covariates"] = [self._covariate(ds, c, s, horizon) for c in ds.covs]
        return out

    @staticmethod
    def _covariate(ds, cov, s: int, horizon: int) -> dict:
        item = dict(
            name=cov.name, kind=cov.kind, cat=cov.categorical, values=Numbers(cov.values[s], DIGITS)
        )
        if cov.is_known:
            values, assumed = known_extended(ds, cov, horizon)
            item.update(
                future=Numbers(values[s, ds.T :], DIGITS), assumed=[int(x) for x in assumed[s]]
            )
        return item


class SeriesRanking:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(self, scope: Scope, variant_key: str) -> list[dict]:
        ds = scope.ds
        panel = self._workbench.evaluations.panel(ds, scope.horizon, scope.context)
        row = panel.row_for(variant_key)
        if row is None:
            return []
        errors = panel.per_series(row, ds.primary)
        return [dict(index=i, id=ds.ids[i], err=number(errors[i], 4)) for i in range(ds.N)]


def _plain(value):
    return value.item() if isinstance(value, np.integer | np.floating) else value
