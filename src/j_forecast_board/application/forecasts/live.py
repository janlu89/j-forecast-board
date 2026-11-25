# SPDX-License-Identifier: Apache-2.0
"""Live forecast of one series, from the end of the data or as if today were an earlier date."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...domain.metrics import actuals, eval_mask, mase_scale, metrics
from ..view_model import Date, Dates, Numbers, dataset_meta
from ..workbench import Scope, Workbench
from .common import DIGITS, band, run

MIN_HISTORY = 8


class LiveForecast:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(self, scope: Scope, series: int, variant_key: str, origin: str | None) -> dict:
        ds, horizon = scope.ds, scope.horizon
        s = self._workbench.series(ds, series)
        variant = self._workbench.variant(ds, variant_key)
        first_cut = max(2 * ds.season, MIN_HISTORY)
        cut = ds.T
        if origin:
            cut = int(ds.dates.searchsorted(pd.Timestamp(origin), side="right"))
            cut = max(min(cut, ds.T), first_cut)
        forecast, seconds = run(self._workbench, ds, [(s, cut)], horizon, scope.context, variant)
        values = forecast.values[0]
        actual = actuals(ds, [(s, cut)], horizon)
        mask = eval_mask(ds, actual, [(s, cut)], horizon)
        scores = {}
        if mask.any():
            scale = np.full(horizon, mase_scale(ds, s, cut))
            scores = metrics(actual[0], forecast.median[0], mask[0], scale, values, forecast.levels)
        shown = max(0, cut - max(6 * horizon, 8 * ds.season))
        end = min(ds.T, cut + horizon)
        return dict(
            meta=dataset_meta(ds),
            id=ds.ids[s],
            horizon=horizon,
            model=self._workbench.label(ds, variant),
            origin=Date(ds, cut - 1),
            dates=Dates(ds, range(shown, end)),
            y=Numbers(ds.y_display(s)[shown:end], DIGITS),
            cut_offset=cut - shown,
            fdates=Dates(ds, range(cut, cut + horizon)),
            forecast=band(values, forecast.levels, wide=True),
            metrics=scores,
            seconds=seconds,
            first=Date(ds, first_cut),
            last=Date(ds, ds.T - 1),
        )
