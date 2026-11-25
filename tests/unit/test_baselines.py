# SPDX-License-Identifier: Apache-2.0
"""Classic baselines the model is compared with."""

from __future__ import annotations

import numpy as np

from j_forecast_board import engine


def test_seasonal_fill_repeats_the_last_cycle():
    history = np.array([1.0, 2, 3, 4, 5, 6])
    assert engine._seasonal_fill(history, 4, 3).tolist() == [4, 5, 6, 4]


def test_seasonal_fill_takes_missing_points_from_an_earlier_cycle():
    history = np.array([1.0, 2, 3, 4, np.nan, 6])
    assert engine._seasonal_fill(history, 4, 3).tolist() == [4, 2, 6, 4]


def test_seasonal_fill_without_any_data_is_zero():
    assert engine._seasonal_fill(np.full(6, np.nan), 2, 3).tolist() == [0, 0]


def test_seasonal_naive_forces_known_closures_to_zero(make_dataset):
    closed = np.zeros((1, 10), dtype=bool)
    closed[0, 7] = True
    ds = make_dataset([1, 2, 3, 4, 5, 6], closed=closed)
    assert engine.baseline(ds, "seasonal_naive", 0, 6, 4).tolist() == [4, 0, 6, 4]


def test_seasonal_mean_averages_up_to_four_cycles(make_dataset):
    ds = make_dataset(np.arange(1.0, 16.0))  # 15 points, season 3
    # last 4 cycles: 4..15 -> column means 8.5, 9.5, 10.5
    assert engine.baseline(ds, "seasonal_mean", 0, 15, 4).tolist() == [8.5, 9.5, 10.5, 8.5]


def test_annual_baseline_repeats_the_value_one_year_back(make_dataset):
    ds = make_dataset(np.arange(1.0, 11.0), year_lag=4)
    assert engine.baseline(ds, "annual", 0, 10, 3).tolist() == [7, 8, 9]


def test_baselines_for_a_daily_dataset_with_a_long_history(make_dataset):
    ds = make_dataset(np.ones(400), season=7, year_lag=364)
    assert engine.baselines_for(ds) == {
        "seasonal_mean": "Seasonal mean (4 cycles)",
        "seasonal_naive": "Naive weekly (last week)",
        "annual": "Naive annual (t−364)",
    }


def test_baselines_skip_the_annual_rule_on_a_short_history(make_dataset):
    ds = make_dataset(np.ones(100), season=7, year_lag=364)
    assert "annual" not in engine.baselines_for(ds)
