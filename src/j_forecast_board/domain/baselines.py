# SPDX-License-Identifier: Apache-2.0
"""Classic forecasting rules the model is compared with."""

from __future__ import annotations

import numpy as np

from .calendar import known_values
from .series import Dataset

PROMO_LOOKBACK = 182  # days of history the weekday x promo mean uses
YEAR_LAGS = {"h": 8736, "D": 364, "7D": 52, "MS": 12, "QS": 4}  # same weekday / period last year
NAIVE_NAMES = {
    7: "Naive weekly (last week)",
    24: "Naive daily (last day)",
    12: "Naive yearly (last year)",
}
REPEAT_NAMES = {7: "Repeat last week", 24: "Repeat last day", 12: "Repeat last year"}


def seasonal_fill(history: np.ndarray, horizon: int, season: int) -> np.ndarray:
    """Repeat the last cycle; missing points are taken from earlier cycles."""
    out = np.full(horizon, np.nan)
    n = len(history)
    for i in range(horizon):
        j = n - season + (i % season)
        while j >= 0 and not np.isfinite(history[j]):
            j -= season
        out[i] = history[j] if j >= 0 else np.nan
    if np.isnan(out).any():
        finite = history[np.isfinite(history)]
        out[np.isnan(out)] = finite[-1] if len(finite) else 0.0
    return out


def baseline_names(ds: Dataset) -> dict[str, str]:
    """The baselines that fit a dataset: key -> label."""
    out = {}
    if ds.promo_baseline:
        out["promo"] = f"Mean weekday × {ds.promo_baseline.lower()}"
    out["seasonal_mean"] = "Seasonal mean (4 cycles)"
    out["seasonal_naive"] = NAIVE_NAMES.get(ds.season, "Seasonal naive")
    if ds.year_lag and ds.year_lag != ds.season and ds.year_lag + 2 * ds.horizon < ds.T:
        out["annual"] = f"Naive annual (t−{ds.year_lag})"
    return out


def baseline(ds: Dataset, name: str, s: int, cut: int, horizon: int) -> np.ndarray:
    """Forecast of series s from cut with the named rule; known closures forced to 0."""
    rules = {
        "seasonal_naive": _seasonal_naive,
        "seasonal_mean": _seasonal_mean,
        "annual": _annual,
        "promo": _weekday_promo,
    }
    if name not in rules:
        raise ValueError(f"Unknown baseline {name}")
    history = ds.Y[s, :cut]
    forecast = rules[name](ds, history, s, cut, horizon)
    bad = ~np.isfinite(forecast)
    if bad.any():
        forecast[bad] = seasonal_fill(history, horizon, ds.season)[bad]
    if ds.closed is not None:
        closures = ds.closed[s, cut : cut + horizon]
        forecast[: len(closures)][closures] = 0.0
    return forecast


def _seasonal_naive(ds, history, s, cut, horizon) -> np.ndarray:
    return seasonal_fill(history, horizon, ds.season)


def _seasonal_mean(ds, history, s, cut, horizon) -> np.ndarray:
    cycles = max(1, min(4, cut // ds.season))
    block = history[cut - cycles * ds.season : cut].reshape(cycles, ds.season)
    with np.errstate(all="ignore"):
        mean = np.nanmean(block, axis=0)
    return np.tile(mean, int(np.ceil(horizon / ds.season)))[:horizon]


def _annual(ds, history, s, cut, horizon) -> np.ndarray:
    source = np.arange(cut, cut + horizon) - ds.year_lag
    return np.where(source >= 0, history[np.clip(source, 0, cut - 1)], np.nan)


def _weekday_promo(ds, history, s, cut, horizon) -> np.ndarray:
    """Mean of the same weekday with the same promo state over the last half year."""
    cov = next(c for c in ds.covs if c.name == ds.promo_baseline)
    promo = known_values(ds, cov, horizon)[s]
    weekday = (np.arange(cut + horizon) + ds.dates[0].day_of_week) % 7
    start = max(0, cut - PROMO_LOOKBACK)
    past, past_day, past_promo = history[start:cut], weekday[start:cut], promo[start:cut]
    out = np.full(horizon, np.nan)
    for i in range(horizon):
        t = cut + i
        same = (past_day == weekday[t]) & (past_promo == promo[t]) & np.isfinite(past)
        if not same.any():
            same = (past_day == weekday[t]) & np.isfinite(past)
        out[i] = past[same].mean() if same.any() else np.nan
    return out


def window_baselines(
    ds: Dataset, y: np.ndarray, start: int, cut: int, horizon: int
) -> dict[str, np.ndarray]:
    """Classic rules that, like the model in the split test, only use the data between start and
    cut."""
    given = y[start:cut]

    def repeat(lag: int) -> np.ndarray:
        out = np.full(horizon, np.nan)
        for i in range(horizon):
            j = cut + i
            while j >= cut:
                j -= lag
            while j >= start and not np.isfinite(y[j]):
                j -= lag
            out[i] = y[j] if j >= start else np.nan
        return out

    out = {}
    lag = YEAR_LAGS.get(ds.freq)
    if lag and cut - start >= lag:
        out["Same period last year"] = repeat(lag)
    out[REPEAT_NAMES.get(ds.season, "Repeat last cycle")] = repeat(ds.season)
    out["Average of the given data"] = np.full(horizon, np.nanmean(given))
    for values in out.values():
        values[~np.isfinite(values)] = np.nanmean(given)
    return out
