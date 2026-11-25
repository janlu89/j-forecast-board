# SPDX-License-Identifier: Apache-2.0
"""Newsvendor scoring of the order planner."""

from __future__ import annotations

import numpy as np
import pytest

from j_forecast_board import planner


def test_score_counts_lost_sales_and_leftovers():
    score = planner._score(np.array([10.0, 10.0]), np.array([8.0, 12.0]), margin=0.4, holding=0.15)
    assert score == pytest.approx(
        dict(fill=0.9, in_stock=0.5, lost=2, leftover=2, leftover_pct=0.1, stock=1.0, cost=1.1)
    )


def test_score_ignores_negative_orders_in_the_stock():
    score = planner._score(np.array([4.0]), np.array([-1.0]), margin=1, holding=1)
    assert score["stock"] == 0
    assert score["lost"] == 5


def test_at_fill_interpolates_along_the_curve():
    curve = [dict(fill=0.9, level=3.0), dict(fill=0.8, level=1.0)]
    assert planner._at_fill(curve, 0.85, "level") == pytest.approx(2.0)


def test_at_fill_outside_the_curve_is_unknown():
    curve = [dict(fill=0.8, level=1.0), dict(fill=0.9, level=3.0)]
    assert planner._at_fill(curve, 0.95, "level") is None
    assert planner._at_fill(curve, 0.5, "level") is None


def test_planner_rejects_out_of_range_settings(make_dataset):
    ds = make_dataset(np.ones(30))
    with pytest.raises(ValueError, match="Target availability"):
        planner.order_plan(ds, 4, 0, None, 0, target=0.2)
    with pytest.raises(ValueError, match="Margin"):
        planner.order_plan(ds, 4, 0, None, 0, margin=0)
