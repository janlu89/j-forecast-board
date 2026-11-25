# SPDX-License-Identifier: Apache-2.0
"""Accuracy metrics of the current engine, checked against values computed by hand."""

from __future__ import annotations

import numpy as np
import pytest

from j_forecast_board.domain import metrics as scoring
from j_forecast_board.domain.forecast import QUANTILE_LEVELS, quantile_index

ACTUAL = np.array([10.0, 20.0, 0.0, 40.0])
PREDICTED = np.array([12.0, 18.0, 5.0, 40.0])
ALL = np.ones(4, dtype=bool)
SCALE = np.full(4, 2.0)


def test_point_metrics_match_hand_computed_values():
    m = scoring.metrics(ACTUAL, PREDICTED, ALL, SCALE)
    assert m["n"] == 4
    assert m["mape"] == pytest.approx((0.2 + 0.1 + 0.0) / 3)  # zero actuals are left out
    assert m["smape"] == pytest.approx((4 / 22 + 4 / 38 + 2 + 0) / 4)
    assert m["rmspe"] == pytest.approx(np.sqrt((0.04 + 0.01 + 0) / 3))
    assert m["wape"] == pytest.approx(9 / 70)
    assert m["mae"] == pytest.approx(2.25)
    assert m["rmse"] == pytest.approx(np.sqrt(33 / 4))
    assert m["bias"] == pytest.approx(5 / 70)
    assert m["mase"] == pytest.approx(1.125)


def test_mask_limits_the_scored_points():
    mask = np.array([True, True, False, False])
    m = scoring.metrics(ACTUAL, PREDICTED, mask)
    assert m["n"] == 2
    assert m["wape"] == pytest.approx(4 / 30)
    assert "mase" not in m


def test_empty_mask_gives_no_metrics():
    assert scoring.metrics(ACTUAL, PREDICTED, np.zeros(4, dtype=bool)) == {}


def test_all_zero_actuals_have_no_percentage_error():
    m = scoring.metrics(np.zeros(3), np.ones(3), np.ones(3, dtype=bool))
    assert m["mape"] is None
    assert m["rmspe"] is None


def quantiles_around(center: np.ndarray, half_width: float) -> np.ndarray:
    levels = np.asarray(QUANTILE_LEVELS)
    return center[:, None] + (levels[None, :] - 0.5) / 0.4 * half_width


def test_quantile_metrics_coverage_width_and_wql():
    q = quantiles_around(np.array([12.0, 18.0, 5.0, 40.0]), 3.0)  # P10/P90 = center -/+ 3
    m = scoring.metrics(ACTUAL, PREDICTED, ALL, quantiles=q)
    assert m["coverage"] == pytest.approx(0.75)  # 0 is outside [2, 8]
    assert m["width"] == pytest.approx(24 / 70)
    levels = np.asarray(QUANTILE_LEVELS)
    errors = ACTUAL[:, None] - q
    pinball = np.maximum(levels * errors, (levels - 1) * errors)
    assert m["wql"] == pytest.approx(2 * pinball.sum() / len(levels) / 70)


def test_quantile_index_picks_the_nearest_level():
    assert QUANTILE_LEVELS[quantile_index(0.5)] == 0.5
    assert QUANTILE_LEVELS[quantile_index(0.11)] == 0.1
    assert QUANTILE_LEVELS[quantile_index(0.98)] == 0.99


def test_mase_scale_is_the_mean_seasonal_change(make_dataset):
    ds = make_dataset([1, 2, 4, 7, 11, 16, 22], season=2)
    # cut 7 > 2 * season: seasonal differences |y[t] - y[t-2]| = 3, 5, 7, 9, 11
    assert scoring.mase_scale(ds, 0, 7) == pytest.approx(7.0)
    # cut 4 <= 2 * season: lag 1 differences 1, 2, 3
    assert scoring.mase_scale(ds, 0, 4) == pytest.approx(2.0)


def test_mase_scale_of_a_flat_series_is_one(make_dataset):
    assert scoring.mase_scale(make_dataset([5, 5, 5, 5, 5, 5, 5]), 0, 7) == 1.0


def test_eval_mask_skips_missing_closed_and_non_positive(make_dataset):
    closed = np.array([[False, False, False, True, False, False, False, False]])
    ds = make_dataset([1, 2, 3, 4, 0, np.nan, 7, 8], closed=closed, positive_only=True)
    items = [(0, 2)]
    actual = scoring.actuals(ds, items, 4)
    assert actual.tolist() == [[3.0, 4.0, 0.0, pytest.approx(np.nan, nan_ok=True)]]
    assert scoring.eval_mask(ds, actual, items, 4).tolist() == [[True, False, False, False]]


def test_actuals_past_the_end_are_missing(make_dataset):
    ds = make_dataset([1, 2, 3])
    assert np.isnan(scoring.actuals(ds, [(0, 2)], 3)[0, 1:]).all()


def test_a_variant_takes_the_canonical_form_of_its_dataset():
    from j_forecast_board.domain.forecast import ModelVariant, all_variants

    chosen = ModelVariant("mistralai/Timestral-5M", use_covariates=False, closed_as_zero=True)
    fitted = chosen.fit_to(has_covariates=False, has_closures=False)
    assert fitted in all_variants(has_covariates=False, has_closures=False)
    assert chosen.fit_to(has_covariates=True, has_closures=True) == chosen
