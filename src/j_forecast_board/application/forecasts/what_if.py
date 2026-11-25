# SPDX-License-Identifier: Apache-2.0
"""What-if: change covariates known in advance over the forecast horizon and compare
with the base."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np

from ...domain.calendar import known_extended
from ...domain.errors import InvalidRequest
from ...domain.forecast import ModelVariant
from ...domain.series import Dataset
from ..view_model import Dates, Numbers, dataset_meta, number
from ..workbench import Scope, Workbench
from .common import DIGITS, band, run

OPENING_COVARIATE = "Open"  # editing it also moves the known closures


@dataclass(frozen=True)
class Edit:
    name: str
    mode: str = "keep"  # keep | set | shift | scale
    value: float = 0
    start: int = 0
    end: int | None = None


@dataclass(frozen=True)
class WhatIfRequest:
    series: int = 0
    variant: str | None = None
    edits: list[Edit] = field(default_factory=list)


class WhatIf:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(self, scope: Scope, request: WhatIfRequest) -> dict:
        ds, horizon = scope.ds, scope.horizon
        s = self._workbench.series(ds, request.series)
        chosen = self._workbench.variant(ds, request.variant)
        variant = ModelVariant(chosen.repo, True, chosen.closed_as_zero)
        known = ds.known_covariates
        if not known:
            raise InvalidRequest(
                "This dataset has no covariates known in advance: what-if needs them."
            )
        base = {c.name: known_extended(ds, c, horizon)[0] for c in known}
        scenario = _apply(base, request.edits, s, ds.T, horizon)
        edited = ds
        if ds.closed is not None and OPENING_COVARIATE in scenario:
            edited = _with_closures(ds, s, scenario[OPENING_COVARIATE][s])
        items = [(s, ds.T)]
        base_forecast, base_seconds = run(
            self._workbench, ds, items, horizon, scope.context, variant
        )
        new_forecast, new_seconds = run(
            self._workbench, edited, items, horizon, scope.context, variant, overrides=scenario
        )
        shown = min(ds.T, max(4 * horizon, 6 * ds.season))
        base_total = float(np.sum(base_forecast.median[0]))
        new_total = float(np.sum(new_forecast.median[0]))
        return dict(
            meta=dataset_meta(edited),
            id=ds.ids[s],
            horizon=horizon,
            model=self._workbench.model.display_name(variant.repo),
            dates=Dates(ds, range(ds.T - shown, ds.T)),
            y=Numbers(edited.y_display(s)[-shown:], DIGITS),
            future_dates=Dates(ds, range(ds.T, ds.T + horizon)),
            base=band(base_forecast.values[0], base_forecast.levels),
            scenario=band(new_forecast.values[0], new_forecast.levels),
            covariates=[_covariate(c, base, scenario, s, ds.T, shown) for c in known],
            totals=dict(
                base=base_total,
                scenario=new_total,
                delta=new_total - base_total,
                pct=(new_total - base_total) / base_total if base_total else None,
            ),
            seconds=base_seconds + new_seconds,
        )


def _apply(
    base: dict[str, np.ndarray], edits: list[Edit], s: int, length: int, horizon: int
) -> dict:
    scenario = {name: values.copy() for name, values in base.items()}
    for edit in edits:
        if edit.name not in scenario or edit.mode == "keep":
            continue
        first = length + max(0, edit.start)
        last = length + min(horizon, edit.end if edit.end is not None else horizon)
        segment = scenario[edit.name][s, first:last]
        changed = {
            "set": np.full_like(segment, edit.value),
            "shift": segment + edit.value,
            "scale": segment * edit.value,
        }.get(edit.mode, segment)
        scenario[edit.name][s, first:last] = changed
    return scenario


def _with_closures(ds: Dataset, s: int, opening: np.ndarray) -> Dataset:
    """A copy of the dataset whose future closures of series s follow the edited opening days."""
    edited = copy.copy(ds)
    edited.closed = ds.closed.copy()
    count = min(edited.closed.shape[1], len(opening)) - ds.T
    edited.closed[s, ds.T : ds.T + count] = opening[ds.T : ds.T + count] == 0
    return edited


def _covariate(cov, base: dict, scenario: dict, s: int, length: int, shown: int) -> dict:
    levels = None
    if cov.categorical:
        levels = sorted(
            {value for value in (number(v, 0) for v in cov.values[s]) if value is not None}
        )
    return dict(
        name=cov.name,
        cat=cov.categorical,
        base=Numbers(base[cov.name][s, length:], DIGITS),
        scenario=Numbers(scenario[cov.name][s, length:], DIGITS),
        hist=Numbers(cov.values[s, -shown:], DIGITS),
        vmin=np.nanmin(cov.values[s]),
        vmax=np.nanmax(cov.values[s]),
        levels=levels,
    )
