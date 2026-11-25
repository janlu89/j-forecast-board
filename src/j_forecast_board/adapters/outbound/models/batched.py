# SPDX-License-Identifier: Apache-2.0
"""Shared part of the model adapters: turn dataset items into batched model inputs.

This is the anti-corruption layer between the domain (datasets, cuts, covariates) and the input
format of Timestral-like models (left-padded context, covariate groups, quantile output).
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod

import numpy as np

from ....application.ports import Progress
from ....domain.calendar import known_values
from ....domain.forecast import MODEL_REPOS, QuantileForecast, SeriesForecastRequest
from ....domain.metrics import closed_mask
from ....domain.series import Dataset


class BatchedQuantileModel(ABC):
    """A ForecastModel whose forecaster takes (batch, context) arrays and returns quantiles."""

    def __init__(self):
        self._forecasters: dict[str, object] = {}
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()  # one forecast at a time: the CPU is the bottleneck

    @abstractmethod
    def _load(self, repo: str):
        """The forecaster object of one model size."""

    def display_name(self, repo: str) -> str:
        return MODEL_REPOS[repo]

    def output_block(self, repo: str) -> int | None:
        return None

    def forecaster(self, repo: str):
        if repo not in MODEL_REPOS:
            raise ValueError(f"Unknown model {repo}")
        with self._load_lock:
            if repo not in self._forecasters:
                self._forecasters[repo] = self._load(repo)
            return self._forecasters[repo]

    def forecast(
        self, ds: Dataset, request: SeriesForecastRequest, progress: Progress | None = None
    ) -> tuple[QuantileForecast, float]:
        forecaster = self.forecaster(request.variant.repo)
        parts = []
        started = time.perf_counter()
        items = request.items
        for i in range(0, len(items), request.chunk):
            chunk = items[i : i + request.chunk]
            context, covariates = build_inputs(ds, chunk, request)
            with self._inference_lock:
                output = forecaster.forecast(
                    context, prediction_length=request.horizon, **covariates
                )
            parts.append(np.asarray(output.quantiles, dtype=np.float32)[:, 0])
            if progress:
                progress(min(len(items), i + request.chunk), len(items))
        values = np.concatenate(parts)
        values[closed_mask(ds, items, request.horizon)] = 0.0
        levels = tuple(float(x) for x in forecaster.quantile_levels)
        return QuantileForecast(values, levels), time.perf_counter() - started

    def forecast_one(
        self, y: np.ndarray, horizon: int, context: int, repo: str, known: np.ndarray | None = None
    ) -> QuantileForecast:
        forecaster = self.forecaster(repo)
        history = y[-context:] if context else y
        covariates = {}
        if known is not None:
            covariates["known_covariates"] = known[
                None, :, len(y) - len(history) : len(y) + horizon
            ]
        with self._inference_lock:
            output = forecaster.forecast(history[None, :], prediction_length=horizon, **covariates)
        levels = tuple(float(x) for x in forecaster.quantile_levels)
        return QuantileForecast(np.asarray(output.quantiles, dtype=np.float32)[0, 0], levels)


def build_inputs(ds: Dataset, items: list[tuple[int, int]], request: SeriesForecastRequest):
    """Context (batch, n) left-padded with NaN, and covariate groups for forecasts of Y[s, :c]."""
    target = ds.target(request.variant.closed_as_zero)
    longest = max(c for _, c in items)
    width = min(request.context, longest) if request.context else longest
    context = np.full((len(items), width), np.nan)
    for i, (s, cut) in enumerate(items):
        start = max(0, cut - width)
        context[i, width - (cut - start) :] = target[s, start:cut]
    groups = {
        "past_covariates": [],
        "known_covariates": [],
        "categorical_past_covariates": [],
        "categorical_known_covariates": [],
    }
    overrides = request.overrides or {}
    for cov in ds.covs if request.variant.use_covariates else []:
        group = ("categorical_" if cov.categorical else "") + (
            "known_covariates" if cov.is_known else "past_covariates"
        )
        if cov.is_known:
            source = overrides.get(cov.name)
            if source is None:
                source = known_values(ds, cov, request.horizon)
            length = width + request.horizon
        else:
            source, length = cov.values, width
        rows = np.full((len(items), length), np.nan)
        for i, (s, cut) in enumerate(items):
            start = max(0, cut - width)
            segment = (
                source[s, start : cut + request.horizon] if cov.is_known else source[s, start:cut]
            )
            rows[i, width - (cut - start) : width - (cut - start) + len(segment)] = segment
        groups[group].append(rows)
    return context, {name: np.stack(rows, axis=1) for name, rows in groups.items() if rows}
