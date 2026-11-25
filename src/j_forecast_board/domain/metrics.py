# SPDX-License-Identifier: Apache-2.0
"""Accuracy metrics and the masks that decide which points are scored."""

from __future__ import annotations

import numpy as np

from .forecast import QUANTILE_LEVELS, quantile_index
from .series import Dataset

PERCENT_METRICS = ("mape", "wape", "smape", "rmspe")


def metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    mask: np.ndarray,
    scale: np.ndarray | None = None,
    quantiles: np.ndarray | None = None,
    levels: tuple[float, ...] = QUANTILE_LEVELS,
) -> dict:
    """Scores where mask is True. actual, predicted, mask, scale: same shape; quantiles: +
    (levels,)."""
    a, p = actual[mask], predicted[mask]
    if a.size == 0:
        return {}
    error = a - p
    size = np.abs(a)
    nonzero = size > 1e-9
    volume = max(np.sum(size), 1e-9)
    with np.errstate(all="ignore"):
        out = dict(
            n=int(a.size),
            mape=float(np.mean(np.abs(error[nonzero]) / size[nonzero])) if nonzero.any() else None,
            smape=float(np.mean(2 * np.abs(error) / np.maximum(np.abs(a) + np.abs(p), 1e-9))),
            rmspe=float(np.sqrt(np.mean((error[nonzero] / a[nonzero]) ** 2)))
            if nonzero.any()
            else None,
            wape=float(np.sum(np.abs(error)) / volume),
            mae=float(np.mean(np.abs(error))),
            rmse=float(np.sqrt(np.mean(error**2))),
            bias=float(np.sum(p - a) / volume),
        )
        if scale is not None:
            out["mase"] = float(np.mean(np.abs(error) / scale[mask]))
        if quantiles is not None:
            q = quantiles[mask]
            low, high = q[:, quantile_index(0.1, levels)], q[:, quantile_index(0.9, levels)]
            out["coverage"] = float(np.mean((a >= low) & (a <= high)))
            out["width"] = float(np.sum(high - low) / volume)
            level_values = np.asarray(levels)
            quantile_error = a[:, None] - q
            pinball = np.maximum(level_values * quantile_error, (level_values - 1) * quantile_error)
            out["wql"] = float(2 * pinball.sum() / len(level_values) / volume)
    return out


def mase_scale(ds: Dataset, s: int, cut: int) -> float:
    """Mean seasonal change of the history before `cut` (lag 1 when it is shorter
    than two cycles)."""
    return naive_error(ds.Y[s, :cut], ds.season if cut > 2 * ds.season else 1)


def naive_error(history: np.ndarray, lag: int) -> float:
    """Mean absolute change over `lag` steps; 1 when there is none (flat or empty history)."""
    changes = np.abs(history[lag:] - history[:-lag])
    changes = changes[np.isfinite(changes)]
    value = float(changes.mean()) if len(changes) else 1.0
    return value if value > 0 else 1.0


def closed_mask(ds: Dataset, items: list[tuple[int, int]], horizon: int) -> np.ndarray:
    mask = np.zeros((len(items), horizon), bool)
    if ds.closed is None:
        return mask
    for i, (s, cut) in enumerate(items):
        segment = ds.closed[s, cut : cut + horizon]
        mask[i, : len(segment)] = segment
    return mask


def eval_mask(
    ds: Dataset, actual: np.ndarray, items: list[tuple[int, int]], horizon: int
) -> np.ndarray:
    """Points to score: known, not on a closed day and, for positive-only datasets, above zero."""
    mask = np.isfinite(actual) & ~closed_mask(ds, items, horizon)
    if ds.positive_only:
        mask &= actual > 0
    return mask


def actuals(ds: Dataset, items: list[tuple[int, int]], horizon: int) -> np.ndarray:
    values = np.full((len(items), horizon), np.nan)
    for i, (s, cut) in enumerate(items):
        segment = ds.Y[s, cut : cut + horizon]
        values[i, : len(segment)] = segment
    return values
