# SPDX-License-Identifier: Apache-2.0
"""View models: what a use case returns, and how it becomes plain data (JSON-ready).

A use case returns a tree of dicts and lists whose leaves are domain values: numbers (also numpy
arrays and scalars), dates, strings. Two small wrappers state what the reader needs to know:
`Numbers(values, digits)` for a series of values shown with a given precision, and `Dates(ds,
steps)`
for steps of a dataset shown as dates. `to_plain` renders the tree: floats rounded (6 digits by
default), non-finite numbers as None, dates in the dataset's format. See docs/adr/0007.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from ..domain.series import Dataset

DEFAULT_DIGITS = 6


@dataclass(frozen=True)
class Number:
    """One value with a precision other than the default."""

    value: object
    digits: int = DEFAULT_DIGITS


@dataclass(frozen=True)
class Numbers:
    """A sequence of values (any shape is flattened) with the given precision."""

    values: object
    digits: int = DEFAULT_DIGITS


@dataclass(frozen=True)
class Dates:
    """Dataset steps shown as dates (steps past the end continue on the dataset's frequency)."""

    ds: Dataset
    steps: Iterable[int]


@dataclass(frozen=True)
class Date:
    ds: Dataset
    step: int


def number(value, digits: int = DEFAULT_DIGITS) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return round(value, digits) if math.isfinite(value) else None


def format_date(ds: Dataset, step: int) -> str:
    stamp = ds.date_at(step)
    return stamp.strftime("%Y-%m-%d %H:%M") if ds.freq == "h" else str(stamp.date())


def format_dates(ds: Dataset, steps: Iterable[int]) -> list[str]:
    steps = list(steps)
    if not steps:
        return []
    beyond = max(steps) - ds.T + 1
    calendar = ds.dates if beyond <= 0 else ds.dates.append(ds.future_dates(beyond))
    stamps = calendar[steps]
    if ds.freq == "h":
        return list(stamps.strftime("%Y-%m-%d %H:%M"))
    return [str(d.date()) for d in stamps]


def to_plain(value):
    """Render a view model as plain Python data (dict, list, str, int, float, bool, None)."""
    if isinstance(value, dict):
        return {key: to_plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_plain(item) for item in value]
    if isinstance(value, Numbers):
        return [number(v, value.digits) for v in np.asarray(value.values, dtype=float).ravel()]
    if isinstance(value, Number):
        return number(value.value, value.digits)
    if isinstance(value, Dates):
        return format_dates(value.ds, value.steps)
    if isinstance(value, Date):
        return format_date(value.ds, value.step)
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        return number(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, pd.Timestamp):
        return str(value)
    if isinstance(value, np.ndarray):
        return to_plain(value.tolist())
    return value


def clean(scores: dict) -> dict:
    """Round every numeric score (not the count `n`) as it is shown, so values derived from the
    shown numbers (e.g. a gain) match them exactly."""
    return {
        key: number(value)
        if isinstance(value, float | int | np.floating | np.integer) and key != "n"
        else value
        for key, value in scores.items()
    }


def dataset_meta(ds: Dataset) -> dict:
    """How a dataset is described to the user."""
    stamp = (lambda d: str(d)) if ds.freq == "h" else (lambda d: str(d.date()))
    return dict(
        key=ds.key,
        name=ds.name,
        description=ds.description,
        unit=ds.unit,
        freq=ds.freq,
        season=ds.season,
        horizon=ds.horizon,
        context=ds.context,
        n=ds.N,
        points=ds.T,
        start=stamp(ds.dates[0]),
        end=stamp(ds.dates[-1]),
        ids=ds.ids,
        id_label=ds.id_label,
        attrs=list(ds.attrs),
        source=ds.source,
        covariates=[dict(name=c.name, kind=c.kind, cat=c.categorical) for c in ds.covs],
        has_known=bool(ds.known_covariates),
        has_closed=ds.closed is not None,
        primary=ds.primary,
        notes=ds.notes,
        agg=ds.agg,
        visibility=ds.visibility,
    )
