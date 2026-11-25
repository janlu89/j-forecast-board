# SPDX-License-Identifier: Apache-2.0
"""Public holidays from the `holidays` library (implements domain.series.HolidayCalendar)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CountryHolidays:
    country: str  # ISO code, e.g. "DE", "US", "IT"

    def flags(self, dates: pd.DatetimeIndex) -> np.ndarray:
        import holidays

        calendar = holidays.country_holidays(self.country, years=sorted(set(dates.year)))
        return np.array([1.0 if d.date() in calendar else 0.0 for d in dates])
