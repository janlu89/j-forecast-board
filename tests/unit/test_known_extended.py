# SPDX-License-Identifier: Apache-2.0
"""How covariates known in advance are extended over the forecast horizon."""

from __future__ import annotations

import numpy as np

from j_forecast_board.adapters.outbound.datasets.holiday_calendar import CountryHolidays
from j_forecast_board.domain import calendar
from j_forecast_board.domain.series import Covariate


def covariate(values, **extra) -> Covariate:
    return Covariate("x", "known", False, np.atleast_2d(np.asarray(values, dtype=float)), **extra)


def test_missing_future_repeats_one_cycle_back(make_dataset):
    ds = make_dataset([0, 0, 0, 0, 0, 0])
    values, assumed = calendar.known_extended(ds, covariate([1, 2, 3, 4, 5, 6]), 4)
    assert values.tolist() == [[1, 2, 3, 4, 5, 6, 4, 5, 6, 4]]
    assert assumed.tolist() == [[1, 1, 1, 1]]


def test_repeat_period_overrides_the_season(make_dataset):
    ds = make_dataset([0, 0, 0, 0, 0, 0], repeat_period=2)
    values, _ = calendar.known_extended(ds, covariate([1, 2, 3, 4, 5, 6]), 3)
    assert values[0, 6:].tolist() == [5, 6, 5]


def test_provided_future_values_are_kept_and_not_flagged(make_dataset):
    ds = make_dataset([0, 0, 0, 0, 0, 0])
    cov = covariate([1, 2, 3, 4, 5, 6], future=np.array([[10.0, np.nan]]))
    values, assumed = calendar.known_extended(ds, cov, 3)
    assert values[0, 6:].tolist() == [10, 5, 6]
    assert assumed.tolist() == [[0, 1, 1]]


def test_calendar_rule_computes_exact_future_values(make_dataset):
    ds = make_dataset([0, 0, 0, 0, 0, 0])  # Monday 1 to Saturday 6 January 2024
    values, assumed = calendar.known_extended(
        ds, covariate(np.zeros(6), rule="calendar:weekday"), 2
    )
    assert values[0, 6:].tolist() == [6, 0]  # Sunday, Monday
    assert assumed.tolist() == [[0, 0]]


def test_zero_rule_fills_the_future_with_zeros(make_dataset):
    ds = make_dataset([0, 0, 0])
    values, assumed = calendar.known_extended(ds, covariate([1, 2, 3], rule="zero"), 2)
    assert values[0, 3:].tolist() == [0, 0]
    assert assumed.tolist() == [[1, 1]]


def test_holiday_flags_use_the_country_calendar():
    import pandas as pd

    dates = pd.date_range("2024-12-24", periods=3, freq="D")
    assert calendar.holiday_flags(dates, CountryHolidays("DE")).tolist() == [0, 1, 1]
    assert calendar.holiday_flags(dates, None).tolist() == [0, 0, 0]
