# SPDX-License-Identifier: Apache-2.0
"""Newsvendor scoring: what a stocking decision costs against the demand that really came.

For every series and period `order` units are stocked; demand above it is a lost sale (lost
margin), stock left over costs a share of its value (holding, markdown, waste).
"""

from __future__ import annotations

import numpy as np

from .errors import InvalidRequest

BUFFERS = np.round(
    np.arange(0.50, 3.001, 0.02), 2
)  # multipliers tried for "forecast + safety buffer"


def score_orders(demand: np.ndarray, order: np.ndarray, margin: float, holding: float) -> dict:
    short = np.maximum(demand - order, 0.0)
    excess = np.maximum(order - demand, 0.0)
    total = max(float(demand.sum()), 1e-9)
    return dict(
        fill=1 - float(short.sum()) / total,
        in_stock=float(np.mean(demand <= order + 1e-9)),
        lost=float(short.sum()),
        leftover=float(excess.sum()),
        leftover_pct=float(excess.sum()) / total,
        stock=float(np.maximum(order, 0).sum()) / total,
        cost=margin * float(short.sum()) + holding * float(excess.sum()),
    )


def value_at_fill(curve: list[dict], target: float, key: str) -> float | None:
    """Interpolate `key` at a fill rate along a curve whose fill rate grows with the order size."""
    points = sorted((c["fill"], c[key]) for c in curve)
    fills = np.array([p[0] for p in points])
    values = np.array([p[1] for p in points])
    if target < fills[0] or target > fills[-1]:
        return None
    return float(np.interp(target, fills, values))


def critical_ratio(margin: float, holding: float) -> float:
    """The newsvendor service level that minimises the expected cost."""
    return margin / (margin + holding)


def check_costs(margin: float, holding: float, target: float) -> None:
    if not (0 < margin <= 10 and 0 <= holding <= 10):
        raise InvalidRequest("Margin must be in (0, 1000%] and leftover cost in [0, 1000%].")
    if not 0.5 <= target <= 0.995:
        raise InvalidRequest("Target availability must be between 50% and 99.5%.")
