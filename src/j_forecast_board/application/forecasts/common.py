# SPDX-License-Identifier: Apache-2.0
"""Helpers shared by the on-demand forecasts."""

from __future__ import annotations

import numpy as np

from ...domain.forecast import ModelVariant, QuantileForecast, SeriesForecastRequest
from ...domain.series import Dataset
from ..view_model import Numbers
from ..workbench import Workbench

DIGITS = 4


def band(values: np.ndarray, levels, wide: bool = False, digits: int = DIGITS) -> dict:
    """Median and P10-P90 (and P5-P95 when wide) of one forecast (horizon, levels)."""
    forecast = QuantileForecast(values, levels)
    out = dict(
        median=Numbers(forecast.median, digits),
        lo=Numbers(forecast.at(0.1), digits),
        hi=Numbers(forecast.at(0.9), digits),
    )
    if wide:
        out.update(lo90=Numbers(forecast.at(0.05), digits), hi90=Numbers(forecast.at(0.95), digits))
    return out


def run(
    workbench: Workbench,
    ds: Dataset,
    items: list[tuple[int, int]],
    horizon: int,
    context: int,
    variant: ModelVariant,
    overrides: dict | None = None,
    chunk: int = 64,
) -> tuple[QuantileForecast, float]:
    request = SeriesForecastRequest(items, horizon, context, variant, overrides, chunk)
    return workbench.model.forecast(ds, request)
