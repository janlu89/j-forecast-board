# SPDX-License-Identifier: Apache-2.0
"""The deterministic stand-in model used by tests and installation checks."""

from __future__ import annotations

import numpy as np
import pytest

from j_forecast_board.adapters.outbound.models.stub_model import QUANTILE_LEVELS, StubForecaster

WEEK = np.array([10.0, 12, 11, 13, 20, 25, 8])


def forecast(context, horizon=5, **covariates) -> np.ndarray:
    return np.asarray(
        StubForecaster().forecast(np.asarray(context), horizon, **covariates).quantiles
    )


def test_output_has_the_shape_of_a_timestral_forecast():
    q = forecast(np.tile(WEEK, (3, 4)), horizon=9)
    assert q.shape == (3, 1, 9, len(QUANTILE_LEVELS))
    assert len(QUANTILE_LEVELS) == 21 and QUANTILE_LEVELS[10] == 0.5


def test_median_repeats_the_detected_weekly_cycle():
    q = forecast(np.tile(WEEK, 6)[None, :], horizon=10)
    median = q[0, 0, :, QUANTILE_LEVELS.index(0.5)]
    assert median.tolist() == pytest.approx(np.resize(WEEK, 10).tolist())


def test_quantiles_grow_with_the_level():
    q = forecast(np.tile(WEEK, 6)[None, :] + np.arange(42) * 0.3, horizon=7)
    assert (np.diff(q[0, 0], axis=-1) >= 0).all()
    assert (q[0, 0, :, -1] > q[0, 0, :, 0]).all()


def test_same_input_gives_the_same_output():
    context = np.tile(WEEK, (2, 5)) + np.arange(35)
    assert np.array_equal(forecast(context), forecast(context))


def test_left_padding_and_missing_values_are_tolerated():
    row = np.concatenate([np.full(10, np.nan), np.tile(WEEK, 4)])
    row[20] = np.nan
    q = forecast(row[None, :])
    assert np.isfinite(q).all()


def test_a_row_without_data_forecasts_zero():
    q = forecast(np.full((1, 12), np.nan), horizon=3)
    assert (q == 0).all()


def test_covariates_are_accepted_and_ignored():
    context = np.tile(WEEK, (1, 4))
    known = np.zeros((1, 2, 28 + 5))
    assert np.array_equal(forecast(context, known_covariates=known), forecast(context))
