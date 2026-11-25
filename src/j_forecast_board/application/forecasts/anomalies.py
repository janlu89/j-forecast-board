# SPDX-License-Identifier: Apache-2.0
"""Anomalies: points of the recent past that fall outside the model's band."""

from __future__ import annotations

import numpy as np

from ...domain.metrics import actuals, eval_mask
from ..view_model import Date, Dates, Numbers, dataset_meta, number
from ..workbench import Scope, Workbench
from .common import DIGITS, run


class Anomalies:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(
        self,
        scope: Scope,
        series: int,
        variant_key: str,
        step: int | None,
        windows: int,
        level: float,
    ) -> dict:
        ds = scope.ds
        s = self._workbench.series(ds, series)
        variant = self._workbench.variant(ds, variant_key)
        step = int(step or ds.season)
        windows = max(1, min(windows, (ds.T - max(3 * ds.season, 2 * step)) // step))
        cuts = [ds.T - k * step for k in range(windows, 0, -1)]
        items = [(s, c) for c in cuts]
        forecast, seconds = run(self._workbench, ds, items, step, scope.context, variant, chunk=32)
        tail = round((1 - level) / 2, 2)
        median = forecast.median.ravel()
        low, high = forecast.at(tail).ravel(), forecast.at(1 - tail).ravel()
        actual = actuals(ds, items, step).ravel()
        scored = eval_mask(ds, actuals(ds, items, step), items, step).ravel()
        width = np.maximum(high - low, 1e-9)
        with np.errstate(all="ignore"):
            score = np.where(
                actual > high,
                (actual - high) / width,
                np.where(actual < low, (actual - low) / width, 0.0),
            )
        score = np.where(scored, score, 0.0)
        flagged = np.where(score != 0)[0]
        start = cuts[0]
        found = sorted(
            [
                dict(
                    date=Date(ds, start + i),
                    actual=number(actual[i]),
                    expected=number(median[i]),
                    lo=number(low[i]),
                    hi=number(high[i]),
                    score=number(score[i]),
                    direction="above" if score[i] > 0 else "below",
                )
                for i in flagged
            ],
            key=lambda x: -abs(x["score"]),
        )
        shown_from = max(0, start - 4 * step)
        return dict(
            meta=dataset_meta(ds),
            id=ds.ids[s],
            model=self._workbench.model.display_name(variant.repo),
            step=step,
            windows=windows,
            level=level,
            dates=Dates(ds, range(shown_from, ds.T)),
            y=Numbers(ds.y_display(s)[shown_from:], DIGITS),
            offset=start - shown_from,
            median=Numbers(median, DIGITS),
            lo=Numbers(low, DIGITS),
            hi=Numbers(high, DIGITS),
            flags=[int(i) for i in flagged],
            anomalies=found,
            rate=len(flagged) / max(1, scored.sum()),
            expected_rate=1 - level,
            seconds=seconds,
        )
