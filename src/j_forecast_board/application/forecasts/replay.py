# SPDX-License-Identifier: Apache-2.0
"""Replay: forecasts of one series made from many past dates, to watch the model work over time."""

from __future__ import annotations

import numpy as np

from ...domain.errors import InvalidRequest
from ...domain.metrics import actuals, eval_mask, mase_scale, metrics
from ..view_model import Dates, Numbers, dataset_meta
from ..workbench import Scope, Workbench
from .common import DIGITS, band, run

MAX_FRAMES = 120


class Replay:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(
        self, scope: Scope, series: int, variant_key: str, frames: int, span: int | None
    ) -> dict:
        ds, horizon = scope.ds, scope.horizon
        s = self._workbench.series(ds, series)
        variant = self._workbench.variant(ds, variant_key)
        min_history = max(3 * ds.season, 2 * horizon, 24)
        span = min(span or max(6 * horizon, 8 * ds.season), ds.T - min_history)
        if span < 1:
            raise InvalidRequest("Series too short for a replay.")
        count = max(2, min(frames, span + 1, MAX_FRAMES))
        cuts = sorted({int(round(c)) for c in np.linspace(ds.T - span, ds.T, count)})
        items = [(s, c) for c in cuts]
        forecast, seconds = run(
            self._workbench, ds, items, horizon, scope.context, variant, chunk=32
        )
        actual = actuals(ds, items, horizon)
        mask = eval_mask(ds, actual, items, horizon)
        out_frames = []
        for k, cut in enumerate(cuts):
            frame = dict(cut=cut, **band(forecast.values[k], forecast.levels))
            if mask[k].any():
                scale = np.full(horizon, mase_scale(ds, s, cut))
                scores = metrics(
                    actual[k],
                    forecast.median[k],
                    mask[k],
                    scale,
                    forecast.values[k],
                    forecast.levels,
                )
                frame.update(
                    err=scores.get(ds.primary),
                    coverage=scores.get("coverage"),
                    seen=int(mask[k].sum()),
                )
            out_frames.append(frame)
        return dict(
            meta=dataset_meta(ds),
            id=ds.ids[s],
            horizon=horizon,
            model=self._workbench.label(ds, variant),
            dates=Dates(ds, range(ds.T)),
            y=Numbers(ds.y_display(s), DIGITS),
            future_dates=Dates(ds, range(ds.T, ds.T + horizon)),
            frames=out_frames,
            seconds=seconds,
        )
