# SPDX-License-Identifier: Apache-2.0
"""A deterministic stand-in for Timestral (JFB_MODEL=stub).

It answers with the same shapes as the real model, so every screen and API route works, but its
numbers are a seasonal naive forecast with a widening band: useful to test an installation, the
UI or the API without downloading weights. They are not forecasts to act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

from .batched import BatchedQuantileModel

QUANTILE_LEVELS = [0.01, *(round(0.05 * i, 2) for i in range(1, 20)), 0.99]  # as Timestral
CANDIDATE_PERIODS = (24, 12, 7, 52, 4)
_Z = np.array([NormalDist().inv_cdf(level) for level in QUANTILE_LEVELS])


@dataclass(frozen=True)
class StubForecast:
    quantiles: np.ndarray  # (batch, 1, horizon, levels), like Timestral's output


class StubForecaster:
    """Seasonal naive median; band from the size of past seasonal changes."""

    quantile_levels = QUANTILE_LEVELS

    def forecast(self, context: np.ndarray, prediction_length: int, **_covariates) -> StubForecast:
        rows = np.atleast_2d(np.asarray(context, dtype=float))
        quantiles = np.stack([_forecast_row(row, prediction_length) for row in rows])
        return StubForecast(quantiles=quantiles[:, None].astype(np.float32))


def _forecast_row(row: np.ndarray, horizon: int) -> np.ndarray:
    history = _drop_left_padding(row)
    if not np.isfinite(history).any():
        return np.zeros((horizon, len(QUANTILE_LEVELS)))
    period = _detect_period(history)
    median = _seasonal_naive(history, period, horizon)
    spread = _spread(history, period) * np.sqrt(1 + np.arange(horizon) // period)
    return median[:, None] + spread[:, None] * _Z[None, :]


def _drop_left_padding(row: np.ndarray) -> np.ndarray:
    finite = np.flatnonzero(np.isfinite(row))
    return row[finite[0] :] if len(finite) else row


def _detect_period(history: np.ndarray) -> int:
    """The candidate cycle with the smallest mean change over the last few cycles."""
    best, best_error = 1, np.inf
    for period in CANDIDATE_PERIODS:
        if len(history) < 2 * period:
            continue
        recent = history[-4 * period :]
        changes = np.abs(recent[period:] - recent[:-period])
        changes = changes[np.isfinite(changes)]
        if len(changes) and changes.mean() < best_error:
            best, best_error = period, changes.mean()
    return best


def _seasonal_naive(history: np.ndarray, period: int, horizon: int) -> np.ndarray:
    last_cycle = history[-period:].copy()
    gaps = ~np.isfinite(last_cycle)
    last_cycle[gaps] = np.nanmean(history)
    return np.resize(last_cycle, horizon)


def _spread(history: np.ndarray, period: int) -> float:
    changes = history[period:] - history[:-period] if len(history) > period else history
    changes = changes[np.isfinite(changes)]
    # 1.25 x mean absolute error of the seasonal naive rule ~ one standard deviation
    spread = 1.25 * float(np.mean(np.abs(changes))) if len(changes) else 0.0
    if spread > 0:
        return spread
    scale = float(np.nanmean(np.abs(history)))
    return 0.1 * scale if scale > 0 else 1.0


class StubModel(BatchedQuantileModel):
    """ForecastModel adapter around the stub: every size answers, and every name says "stub"."""

    def __init__(self):
        super().__init__()
        self._stub = StubForecaster()

    def display_name(self, repo: str) -> str:
        return f"{super().display_name(repo)} · stub"

    def is_available(self, repo: str) -> bool:
        return True

    def _load(self, repo: str) -> StubForecaster:
        return self._stub
