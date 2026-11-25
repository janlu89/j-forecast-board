# SPDX-License-Identifier: Apache-2.0
"""How a dataset is backtested: holdout windows, and groups of series for the breakdown."""

from __future__ import annotations

import numpy as np

from .series import Dataset

PANEL_SIZE = 20  # from this many series on, one holdout window is enough


def holdout_cuts(ds: Dataset, horizon: int) -> list[int]:
    """Cut points of the holdout windows: the last `horizon` steps, repeated up to 6 times for
    small data."""
    windows = 1 if ds.N >= PANEL_SIZE else 6
    windows = max(1, min(windows, (ds.T - max(3 * ds.season, 2 * horizon)) // horizon))
    return [ds.T - k * horizon for k in range(windows, 0, -1)]


def context_length(ds: Dataset, requested: int | None) -> int:
    return ds.context if requested is None else int(requested)


def attribute_groups(values: list) -> list[dict]:
    """Groups of series for a breakdown: quartiles of a numeric attribute, or up to 12 labels."""
    values = list(values)
    if all(isinstance(x, int | float | np.integer | np.floating) for x in values):
        numbers = np.array(values, float)
        numbers = np.where(numbers < 0, np.nan, numbers)
        if np.isfinite(numbers).sum() < 8:
            return []
        edges = np.nanquantile(numbers, [0, 0.25, 0.5, 0.75, 1])
        groups = []
        for i in range(4):
            low, high = edges[i], edges[i + 1]
            members = [
                j
                for j in range(len(numbers))
                if np.isfinite(numbers[j])
                and (low <= numbers[j] <= high if i == 3 else low <= numbers[j] < high)
            ]
            groups.append(dict(label=f"{low:,.0f}–{high:,.0f}", idx=members))
        return [g for g in groups if g["idx"]]
    labels = sorted(set(map(str, values)))
    if len(labels) > 12:
        return []
    return [
        dict(label=lab, idx=[j for j, x in enumerate(values) if str(x) == lab]) for lab in labels
    ]
