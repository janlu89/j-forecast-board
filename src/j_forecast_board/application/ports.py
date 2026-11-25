# SPDX-License-Identifier: Apache-2.0
"""Ports: what the use cases need from the outside world. Adapters implement them."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import numpy as np

from ..domain.forecast import QUANTILE_LEVELS, QuantileForecast, SeriesForecastRequest
from ..domain.series import Dataset

Progress = Callable[[int, int], None]  # (done, total)


class ForecastModel(Protocol):
    """A forecasting model family with several sizes (repos)."""

    def display_name(self, repo: str) -> str:
        """Name shown to the user, e.g. "Timestral-28M"."""
        ...

    def is_available(self, repo: str) -> bool:
        """True when the weights are on this PC (no download needed)."""
        ...

    def forecast(
        self, ds: Dataset, request: SeriesForecastRequest, progress: Progress | None = None
    ) -> tuple[QuantileForecast, float]:
        """Quantiles (items, horizon, levels) with known closures forced to 0, and the seconds
        taken.

        Raises ModelUnavailable when the weights are missing and cannot be downloaded."""
        ...

    def forecast_one(
        self, y: np.ndarray, horizon: int, context: int, repo: str, known: np.ndarray | None = None
    ) -> QuantileForecast:
        """Forecast an arbitrary single series; known: (covariates, len(y) + horizon)."""
        ...

    def output_block(self, repo: str) -> int | None:
        """Steps the model produces in one pass, if it has such a notion."""
        ...


@dataclass
class BacktestResult:
    """Cached evaluation of one dataset, horizon, context and model variant."""

    bt: np.ndarray  # (N, windows, H, levels) holdout forecasts
    fut: np.ndarray  # (N, H, levels) forecasts of the future
    cuts: np.ndarray
    secs: float  # compute time of the holdout part
    secs_total: float
    meta: dict
    total_bt: np.ndarray | None = None  # direct forecast of the total (panels only)
    total_fut: np.ndarray | None = None
    levels: tuple[float, ...] = QUANTILE_LEVELS


class ResultStore(Protocol):
    def find(
        self, ds: Dataset, horizon: int, context: int, variant_key: str
    ) -> BacktestResult | None:
        """The stored result, or None when there is none (a damaged file counts as none)."""
        ...

    def save(
        self, ds: Dataset, horizon: int, context: int, variant_key: str, result: BacktestResult
    ) -> None:
        """Store atomically; datasets with persist=False are kept in memory only."""
        ...

    def delete_for(self, ds: Dataset) -> None: ...


@dataclass
class JobState:
    key: tuple
    info: dict
    priority: int
    state: str = "queued"  # queued | running | done | error
    done: int = 0
    total: int = 0
    started: float | None = None
    eta: float | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        head = {k: v for k, v in self.info.items() if k != "series"}
        return dict(
            **head,
            state=self.state,
            done=self.done,
            total=self.total,
            started=self.started,
            eta=self.eta,
            error=self.error,
            series=self.info.get("series"),
            priority=self.priority,
        )

    @property
    def active(self) -> bool:
        return self.state in ("queued", "running")


class JobRunner(Protocol):
    """Runs background work one job at a time; a lower priority number runs first."""

    def submit(
        self, key: tuple, work: Callable[[JobState], None], priority: int, info: dict
    ) -> JobState: ...

    def get(self, key: tuple) -> JobState | None: ...

    def all(self) -> list[JobState]: ...


class DatasetCatalog(Protocol):
    def list(self) -> list[Dataset]: ...

    def get(self, key: str) -> Dataset:
        """Raises NotFound."""
        ...

    def register(self, ds: Dataset) -> None: ...

    def remove(self, key: str) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class AuditLog(Protocol):
    def record(self, event: str, **fields) -> None:
        """Append one event; never raises into the caller; never receives data values."""
        ...
