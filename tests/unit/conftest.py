# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def make_dataset():
    """Build a small legacy Dataset; dates start on Monday 2024-01-01."""
    from j_forecast_board.domain.series import Dataset

    def build(values, season=3, freq="D", **extra):
        values = np.atleast_2d(np.asarray(values, dtype=float))
        dates = pd.date_range("2024-01-01", periods=values.shape[1], freq=freq)
        return Dataset("unit", "Unit test", "", "units", freq, season, 4, 0, dates, values, **extra)

    return build
