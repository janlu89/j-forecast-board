# SPDX-License-Identifier: Apache-2.0
"""Split test: give the model a stretch of history, forecast what comes after, compare with
reality."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ...domain.baselines import window_baselines
from ...domain.errors import InvalidRequest
from ...domain.forecast import QuantileForecast
from ...domain.metrics import eval_mask, metrics, naive_error
from ..view_model import Date, Dates, Numbers, clean, dataset_meta
from ..workbench import Workbench
from .common import run

MAX_STEPS = 4000
DEFAULT_YEARS_SHOWN = 5
DEFAULT_YEARS_GIVEN = 2
DIGITS = 3
MAX_ERROR = 1e9


@dataclass(frozen=True)
class SplitRequest:
    series: int = 0
    variant: str | None = None
    start: str | None = None  # first date given to the model
    split: str | None = None  # last date given to the model
    end: str | None = None  # last date to forecast


class SplitTest:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(self, dataset: str, request: SplitRequest) -> dict:
        ds = self._workbench.catalog.get(dataset)
        s = self._workbench.series(ds, request.series)
        variant = self._workbench.variant(ds, request.variant)
        season, per_year = ds.season, ds.steps_per_year

        def step(date: str | None, default: int, side: str = "left") -> int:
            return (
                default if not date else int(ds.dates.searchsorted(pd.Timestamp(date), side=side))
            )

        end = min(ds.T, step(request.end, ds.T, "right"))
        start = max(0, step(request.start, max(0, end - DEFAULT_YEARS_SHOWN * per_year)))
        cut = min(end - 1, step(request.split, start + DEFAULT_YEARS_GIVEN * per_year, "right"))
        if cut - start < 2 * season:
            raise InvalidRequest(f"Give the model at least {2 * season} points (two cycles).")
        horizon = end - cut
        if horizon > MAX_STEPS:
            raise InvalidRequest(
                f"{horizon} steps to forecast: choose a shorter range (max 4,000 steps)."
            )

        forecast, seconds = run(self._workbench, ds, [(s, cut)], horizon, cut - start, variant)
        q = QuantileForecast(forecast.values[0], forecast.levels)
        median = q.median
        actual = ds.Y[s, cut:end]
        mask = eval_mask(ds, actual[None, :], [(s, cut)], horizon)[0]
        # MASE relative to the naive error on the data the model saw
        scale = np.full(horizon, naive_error(ds.Y[s, start:cut], season))
        model_name = self._workbench.model.display_name(variant.repo)
        rows = [
            dict(
                name=model_name
                + ("" if variant.use_covariates or not ds.covs else " · no covariates"),
                kind="timestral",
                **clean(metrics(actual, median, mask, scale, q.values, q.levels)),
            )
        ]
        baselines = window_baselines(ds, ds.Y[s], start, cut, horizon)
        for name, predicted in baselines.items():
            if ds.closed is not None:
                predicted[ds.closed[s, cut:end]] = 0.0
            rows.append(
                dict(name=name, kind="baseline", **clean(metrics(actual, predicted, mask, scale)))
            )
        rows.sort(key=lambda x: x.get(ds.primary) if x.get(ds.primary) is not None else MAX_ERROR)

        forecast_dates = ds.dates[cut:end]
        best_baseline = next(x["name"] for x in rows if x["kind"] == "baseline")
        y = ds.y_display(s)
        return dict(
            meta=dataset_meta(ds),
            id=ds.ids[s],
            model=self._workbench.label(ds, variant),
            start=Date(ds, start),
            split=Date(ds, cut - 1),
            end=Date(ds, end - 1),
            first=Date(ds, 0),
            last=Date(ds, ds.T - 1),
            dates=Dates(ds, range(start, end)),
            y=Numbers(y[start:end], DIGITS),
            cut=cut - start,
            forecast=dict(
                median=Numbers(median, DIGITS),
                lo=Numbers(q.at(0.1), DIGITS),
                hi=Numbers(q.at(0.9), DIGITS),
                lo90=Numbers(q.at(0.05), DIGITS),
                hi90=Numbers(q.at(0.95), DIGITS),
            ),
            baselines={name: Numbers(values, DIGITS) for name, values in baselines.items()},
            leaderboard=rows,
            periods=_error_by_period(ds, forecast_dates, actual, q, mask, scale, baselines),
            table=_period_totals(ds, forecast_dates, actual, q, baselines[best_baseline]),
            best_baseline=best_baseline,
            how=self._how(ds, variant, q, start, cut, horizon, per_year),
            seconds=seconds,
            primary=ds.primary,
            agg=ds.agg,
        )

    def _how(self, ds, variant, q: QuantileForecast, start, cut, horizon, per_year) -> dict:
        """How the model did it: how much it saw, how far it forecast, how the band widened."""
        given, season = cut - start, ds.season
        median, width = q.median, q.at(0.9) - q.at(0.1)
        k = max(1, horizon // 10)
        width_first = np.nanmean(width[:k]) / max(np.nanmean(np.abs(median[:k])), 1e-9)
        width_last = np.nanmean(width[-k:]) / max(np.nanmean(np.abs(median[-k:])), 1e-9)
        block = self._workbench.model.output_block(variant.repo)
        covariates = [c.name for c in ds.covs] if variant.use_covariates else []
        known = [c.name for c in ds.known_covariates] if variant.use_covariates else []
        return dict(
            context=given,
            horizon=horizon,
            ratio=horizon / given,
            years_seen=given / per_year,
            years_forecast=horizon / per_year,
            cycles=given / season,
            season=season,
            covariates=covariates,
            known=known,
            width_first=width_first,
            width_last=width_last,
            block=block,
            blocks=int(np.ceil(horizon / block)) if block else None,
            quantiles=len(q.levels),
        )


def _error_by_period(ds, dates, actual, q: QuantileForecast, mask, scale, baselines) -> list[dict]:
    """Error by year / quarter / month of the forecast."""
    span_days = (dates[-1] - dates[0]).days
    if span_days > 540:
        code, label = "Y", lambda p: str(p.year)
    elif span_days > 120:
        code, label = "Q", lambda p: f"{p.year} Q{p.quarter}"
    else:
        code, label = "M", lambda p: p.strftime("%b %Y")
    periods = pd.PeriodIndex(dates, freq=code)
    median, low, high = q.median, q.at(0.1), q.at(0.9)
    out = []
    for period in periods.unique():
        inside = periods == period
        if not (mask & inside).any():
            continue
        item = dict(label=label(period), steps=int(inside.sum()))
        item["Timestral"] = metrics(
            actual[inside], median[inside], mask[inside], scale[inside]
        ).get(ds.primary)
        for name, predicted in baselines.items():
            item[name] = metrics(
                actual[inside], predicted[inside], mask[inside], scale[inside]
            ).get(ds.primary)
        item["width"] = np.nanmean(high[inside] - low[inside]) / max(
            np.nanmean(np.abs(actual[inside])), 1e-9
        )
        out.append(item)
    return out


def _period_totals(ds, dates, actual, q: QuantileForecast, baseline) -> list[dict]:
    """Totals per month (daily or hourly data) or per year (monthly data)."""
    monthly = ds.freq in ("h", "D", "7D")
    periods = pd.PeriodIndex(dates, freq="M" if monthly else "Y")
    if ds.agg == "sum":

        def total(values, inside):
            return float(np.nansum(values[inside]))
    else:

        def total(values, inside):
            return float(np.nanmean(values[inside]))

    median, low, high = q.median, q.at(0.1), q.at(0.9)
    out = []
    for period in periods.unique():
        inside = (periods == period) & np.isfinite(actual)
        if not inside.any():
            continue
        real, predicted, classic = (
            total(actual, inside),
            total(median, inside),
            total(baseline, inside),
        )
        out.append(
            dict(
                period=period.strftime("%b %Y") if monthly else str(period.year),
                actual=real,
                forecast=predicted,
                lo=total(low, inside),
                hi=total(high, inside),
                err=(predicted - real) / real if real else None,
                baseline=classic,
                base_err=(classic - real) / real if real else None,
            )
        )
    return out
