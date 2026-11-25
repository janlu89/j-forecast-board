# SPDX-License-Identifier: Apache-2.0
"""Datasets: panels of time series on a common date grid, with their covariates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import numpy as np
import pandas as pd

STEPS_PER_YEAR = {"h": 8760, "D": 365, "7D": 52, "MS": 12, "QS": 4}
PERIOD_NAME = {"h": "hour", "D": "day", "7D": "week", "MS": "month", "QS": "quarter"}


class Visibility(StrEnum):
    """Built-in datasets are public; whatever a user uploads is private."""

    PUBLIC = "public"
    PRIVATE = "private"


class HolidayCalendar(Protocol):
    """Public holidays of one country (implemented outside the domain)."""

    def flags(self, dates: pd.DatetimeIndex) -> np.ndarray:
        """1.0 on a public holiday, else 0.0, one value per date."""
        ...


@dataclass
class Covariate:
    name: str
    kind: str  # "past" (known up to today) | "known" (known in advance, also over the future)
    categorical: bool
    values: np.ndarray  # (N, T)
    future: np.ndarray | None = None  # (N, F) explicitly provided future values (NaN = unknown)
    rule: str = "repeat"  # how to fill unknown future values: "calendar:<fn>" | "repeat" | "zero"

    @property
    def is_known(self) -> bool:
        return self.kind == "known"


@dataclass
class Dataset:
    key: str
    name: str
    description: str
    unit: str
    freq: str
    season: int
    horizon: int
    context: int  # default context length (0 = all)
    dates: pd.DatetimeIndex
    Y: np.ndarray  # (N, T) target, NaN = missing  # noqa: N815 - the conventional name of a panel
    ids: list[str] = field(default_factory=lambda: ["series"])
    id_label: str = "Series"
    attrs: dict[str, list] = field(default_factory=dict)  # per-series attributes
    covs: list[Covariate] = field(default_factory=list)
    closed: np.ndarray | None = (
        None  # (N, T + F) True = known closure (forecast forced to 0, not scored)
    )
    positive_only: bool = False  # score only points with actual > 0 (Kaggle Rossmann rule)
    primary: str = "mape"  # headline metric
    kaggle: bool = False  # show RMSPE as in the Kaggle competition
    repeat_period: int | None = None
    holidays: HolidayCalendar | None = None
    year_lag: int | None = None  # lag for the "same period last year" baseline
    promo_baseline: str | None = None  # name of a known covariate for the weekday x promo baseline
    notes: list[str] = field(default_factory=list)
    source: str = ""
    persist: bool = True  # cache evaluation results on disk
    agg: str = (
        "sum"  # how to aggregate over periods: "sum" (sales, energy) or "mean" (temperatures)
    )
    visibility: Visibility = Visibility.PUBLIC
    _future_cache: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def N(self) -> int:  # noqa: N802 - number of series, as in the panel notation
        return self.Y.shape[0]

    @property
    def T(self) -> int:  # noqa: N802 - number of time steps
        return self.Y.shape[1]

    @property
    def known_covariates(self) -> list[Covariate]:
        return [c for c in self.covs if c.is_known]

    @property
    def is_private(self) -> bool:
        return self.visibility is Visibility.PRIVATE

    @property
    def steps_per_year(self) -> int:
        return STEPS_PER_YEAR.get(self.freq, 365)

    def future_dates(self, horizon: int) -> pd.DatetimeIndex:
        return pd.date_range(self.dates[-1], periods=horizon + 1, freq=self.freq)[1:]

    def date_at(self, step: int) -> pd.Timestamp:
        """Date of a step; steps past the end continue on the dataset's frequency."""
        if step < self.T:
            return self.dates[step]
        return self.future_dates(step - self.T + 1)[-1]

    def y_display(self, s: int) -> np.ndarray:
        """Target as a person would read it: known closures shown as 0."""
        y = self.Y[s].copy()
        if self.closed is not None:
            y[self.closed[s, : self.T] & np.isnan(y)] = 0.0
        return y

    def target(self, closed_as_zero: bool) -> np.ndarray:
        """The history the model sees: closed days as missing (default) or as zero sales."""
        if closed_as_zero and self.closed is not None:
            return np.where(self.closed[:, : self.T] & np.isnan(self.Y), 0.0, self.Y)
        return self.Y

    def total(self) -> np.ndarray:
        """Sum over all series (missing / closed = 0); NaN only where no series has data."""
        tot = np.nansum(self.Y, axis=0)
        return np.where(np.isnan(self.Y).all(axis=0) & (self.closed is None), np.nan, tot)

    def series_index(self, series_id: str) -> int | None:
        try:
            return self.ids.index(series_id)
        except ValueError:
            return None
