# SPDX-License-Identifier: Apache-2.0
"""Overview: how good is each model on the holdout, and where do the errors come from."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...domain.calendar import cycle_position
from ...domain.evaluation import attribute_groups
from ...domain.forecast import quantile_index
from ...domain.metrics import metrics
from ..evaluations import Panel
from ..view_model import Date, clean, dataset_meta, number
from ..workbench import Scope, Workbench

CALIBRATION_BANDS = [
    (0.4, 0.6),
    (0.3, 0.7),
    (0.25, 0.75),
    (0.2, 0.8),
    (0.1, 0.9),
    (0.05, 0.95),
    (0.01, 0.99),
]
SHOWN_SERIES = 10
MAX_ERROR = 1e9  # sorts rows without a score last


class Overview:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(self, scope: Scope) -> dict:
        ds, horizon = scope.ds, scope.horizon
        panel = self._workbench.evaluations.panel(ds, horizon, scope.context)
        primary = ds.primary
        leaderboard = _leaderboard(panel)
        by_key = {row["key"]: row for row in leaderboard}

        def error(row):
            value = by_key[row["key"]].get(primary)
            return value if value is not None else MAX_ERROR

        best_model = min(panel.model_rows, key=error) if panel.model_rows else None
        best_baseline = min(panel.baseline_rows, key=error)
        out = dict(
            meta=dataset_meta(ds),
            H=horizon,
            L=scope.context,
            primary=primary,
            windows=len(panel.cuts),
            holdout=[dict(start=Date(ds, c), end=Date(ds, c + horizon - 1)) for c in panel.cuts],
            future=dict(start=Date(ds, ds.T), end=Date(ds, ds.T + horizon - 1)),
            leaderboard=leaderboard,
            by_step=_error_by_step(panel),
            calendar=_error_by_calendar(
                panel, [r for r in (best_model, best_baseline) if r is not None]
            ),
            calibration=_calibration(panel),
            best=best_model and best_model["name"],
            best_baseline=best_baseline["name"],
            scored_points=int(panel.M.sum()),
        )
        if best_model is not None:
            model, base = by_key[best_model["key"]], by_key[best_baseline["key"]]
            out["kpi"] = dict(
                model=model,
                baseline=base,
                gain=number(1 - model[primary] / base[primary]) if base.get(primary) else None,
                secs_total=number(float(best_model["res"].secs_total)),
            )
        if len(panel.cuts) > 1:
            out["per_window"] = _error_by_window(panel)
        if ds.N > 1 and best_model is not None:
            out.update(_panel_breakdown(panel, best_model, best_baseline))
        return out


def _leaderboard(panel: Panel) -> list[dict]:
    rows = [
        dict(
            name=row["name"],
            kind=row["kind"],
            key=row["key"],
            secs=number(row["secs"]),
            **clean(panel.score(row)),
        )
        for row in panel.rows
    ]
    primary = panel.ds.primary
    rows.sort(key=lambda r: r.get(primary) if r.get(primary) is not None else MAX_ERROR)
    return rows


def _error_by_step(panel: Panel) -> dict[str, list]:
    primary = panel.ds.primary
    out = {}
    for row in panel.rows:
        values = []
        for h in range(panel.H):
            scores = metrics(
                panel.A[:, :, h], row["P"][:, :, h], panel.M[:, :, h], panel.scale[:, :, h]
            )
            values.append(number(scores.get(primary)) if scores else None)
        out[row["name"]] = values
    return out


def _error_by_calendar(panel: Panel, rows: list[dict]) -> dict:
    ds, primary = panel.ds, panel.ds.primary
    name, labels, position_of = cycle_position(ds)
    steps = np.array([[[c + h for h in range(panel.H)] for c in panel.cuts]] * ds.N)
    calendar = np.concatenate([ds.dates, ds.future_dates(panel.H)])
    positions = position_of(pd.DatetimeIndex(calendar[steps.ravel()])).reshape(steps.shape)
    values = {}
    for row in rows:
        errors = []
        for k in range(len(labels)):
            selected = panel.M & (positions == k)
            scores = metrics(panel.A, row["P"], selected, panel.scale) if selected.any() else {}
            errors.append(number(scores.get(primary)) if scores else None)
        values[row["name"]] = errors
    return dict(name=name, labels=labels, values=values)


def _calibration(panel: Panel) -> dict[str, list]:
    out = {}
    for row in panel.model_rows:
        actual, quantiles, levels = panel.A[panel.M], row["Q"][panel.M], row["levels"]
        points = []
        for low, high in CALIBRATION_BANDS:
            inside = (actual >= quantiles[:, quantile_index(low, levels)]) & (
                actual <= quantiles[:, quantile_index(high, levels)]
            )
            points.append(dict(nominal=round(high - low, 2), observed=number(np.mean(inside))))
        out[row["name"]] = points
    return out


def _error_by_window(panel: Panel) -> dict:
    primary = panel.ds.primary
    return dict(
        labels=[Date(panel.ds, c) for c in panel.cuts],
        values={
            row["name"]: [
                number(panel.score(row, (slice(None), w)).get(primary))
                for w in range(len(panel.cuts))
            ]
            for row in panel.rows
        },
    )


def _panel_breakdown(panel: Panel, best_model: dict, best_baseline: dict) -> dict:
    ds, primary = panel.ds, panel.ds.primary
    model_errors = panel.per_series(best_model, primary)
    baseline_errors = panel.per_series(best_baseline, primary)
    out = dict(
        distribution={
            best_model["name"]: [number(x, 4) for x in model_errors],
            best_baseline["name"]: [number(x, 4) for x in baseline_errors],
        }
    )
    order = np.argsort(np.where(np.isfinite(model_errors), model_errors, np.inf))
    scored = [i for i in order if np.isfinite(model_errors[i])]

    def entry(i):
        return dict(
            index=int(i),
            id=ds.ids[i],
            model=number(model_errors[i]),
            baseline=number(baseline_errors[i]),
        )

    out["best_series"] = [entry(i) for i in scored[:SHOWN_SERIES]]
    out["worst_series"] = [entry(i) for i in scored[::-1][:SHOWN_SERIES]]
    out["breakdown"] = {}
    for attribute, values in ds.attrs.items():
        groups = attribute_groups(values)
        if not groups:
            continue
        rows = [*panel.model_rows, best_baseline]
        out["breakdown"][attribute] = dict(
            labels=[f"{g['label']} ({len(g['idx'])})" for g in groups],
            values={
                row["name"]: [
                    number(panel.score(row, np.array(g["idx"])).get("wape")) for g in groups
                ]
                for row in rows
            },
        )
    total = ds.total()
    actual = np.stack([total[c : c + panel.H] for c in panel.cuts])
    mask = np.isfinite(actual) & (actual > 0)
    bottom_up = best_model["P"].sum(axis=0)
    out["total_kpi"] = number(metrics(actual, bottom_up, mask).get("mape"))
    return out
