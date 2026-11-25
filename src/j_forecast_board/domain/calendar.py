# SPDX-License-Identifier: Apache-2.0
"""Calendar features and the future values of covariates known in advance."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .series import Covariate, Dataset, HolidayCalendar

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def holiday_flags(dates: pd.DatetimeIndex, holidays: HolidayCalendar | None) -> np.ndarray:
    return np.zeros(len(dates)) if holidays is None else holidays.flags(dates)


def calendar_values(
    rule: str, dates: pd.DatetimeIndex, holidays: HolidayCalendar | None
) -> np.ndarray:
    """Values of a calendar covariate ("calendar:weekday", ":hour", ":month", ":holiday",
    ":workingday")."""
    feature = rule.split(":", 1)[1]
    if feature == "weekday":
        return dates.day_of_week.to_numpy(float)
    if feature == "hour":
        return dates.hour.to_numpy(float)
    if feature == "month":
        return dates.month.to_numpy(float)
    flags = holiday_flags(dates, holidays)
    if feature == "holiday":
        return flags
    if feature == "workingday":
        return ((dates.day_of_week < 5) & (flags == 0)).astype(float)
    raise ValueError(f"Unknown calendar rule {rule}")


def known_extended(ds: Dataset, cov: Covariate, horizon: int) -> tuple[np.ndarray, np.ndarray]:
    """(N, T + H) values over history and future, and (N, H) flags: 1 = assumed (not provided)."""
    n_series, length = ds.N, ds.T
    future = np.full((n_series, horizon), np.nan)
    if cov.future is not None:
        given = min(horizon, cov.future.shape[1])
        future[:, :given] = cov.future[:, :given]
    missing = ~np.isfinite(future)
    assumed = missing.astype(float)
    if missing.any():
        if cov.rule.startswith("calendar:"):
            exact = calendar_values(cov.rule, ds.future_dates(horizon), ds.holidays)
            future = np.where(missing, exact[None, :], future)
            assumed[:] = 0  # calendar values are known exactly
        elif cov.rule == "zero":
            future = np.where(missing, 0.0, future)
        else:  # same period one cycle back (e.g. same weekday last year)
            period = (
                ds.repeat_period if ds.repeat_period and ds.repeat_period < length else ds.season
            )
            fallback = _last_finite(cov.values)
            for i in range(horizon):
                j = length + i
                while j >= length:
                    j -= period
                column = cov.values[:, j] if j >= 0 else np.full(n_series, np.nan)
                fill = np.where(np.isfinite(column), column, fallback)
                future[:, i] = np.where(missing[:, i], fill, future[:, i])
    return np.concatenate([cov.values, future], axis=1), assumed


def known_values(ds: Dataset, cov: Covariate, horizon: int) -> np.ndarray:
    """Cached (N, T + H) values of a known covariate."""
    key = (cov.name, horizon)
    if key not in ds._future_cache:
        ds._future_cache[key] = known_extended(ds, cov, horizon)[0]
    return ds._future_cache[key]


def aggregated_known(ds: Dataset, horizon: int) -> np.ndarray | None:
    """Known covariates of the total: share of series with each flag (e.g. % of stores open)."""
    rows = [np.nanmean(known_values(ds, c, horizon), axis=0) for c in ds.known_covariates]
    return np.stack(rows) if rows else None


def cycle_position(ds: Dataset) -> tuple[str, list[str], callable]:
    """How to group forecast errors by calendar position: name, labels, date -> position."""
    if ds.freq == "h":
        return "hour of day", [f"{h:02d}" for h in range(24)], lambda d: d.hour.to_numpy()
    if ds.freq == "D":
        return "weekday", WEEKDAY_LABELS, lambda d: d.day_of_week.to_numpy()
    return "month", MONTH_LABELS, lambda d: d.month.to_numpy() - 1


def _last_finite(values: np.ndarray) -> np.ndarray:
    out = np.zeros(values.shape[0])
    for i in range(values.shape[0]):
        finite = values[i][np.isfinite(values[i])]
        out[i] = finite[-1] if len(finite) else 0.0
    return out
