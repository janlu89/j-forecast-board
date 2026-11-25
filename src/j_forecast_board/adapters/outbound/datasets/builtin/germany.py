# SPDX-License-Identifier: Apache-2.0
"""Open Power System Data, daily German consumption."""

from __future__ import annotations

import io

import pandas as pd

from .....domain.series import Covariate, Dataset
from ..downloader import Downloader
from ..holiday_calendar import CountryHolidays


def load(downloader: Downloader) -> Dataset:
    raw = downloader.fetch(
        "https://raw.githubusercontent.com/jenfly/opsd/master/opsd_germany_daily.csv",
        "opsd_germany_daily.csv",
    )
    df = pd.read_csv(io.BytesIO(raw), parse_dates=["Date"])
    d = pd.DatetimeIndex(df["Date"])
    covs = [
        Covariate(
            "Public holiday (DE)",
            "known",
            True,
            CountryHolidays("DE").flags(d)[None, :],
            rule="calendar:holiday",
        )
    ]
    return Dataset(
        "germany",
        "Germany electricity · daily, 12 years",
        "Total electricity consumption in Germany per day (GWh), 2006-2017, from Open Power "
        "System Data. "
        "Public holidays are a covariate known in advance. Long history: ideal for the Split test.",
        "GWh / day",
        "D",
        7,
        28,
        0,
        d,
        df["Consumption"].to_numpy(float)[None, :],
        ids=["DE"],
        id_label="Country",
        covs=covs,
        repeat_period=364,
        year_lag=364,
        holidays=CountryHolidays("DE"),
        source="Open Power System Data (OPSD)",
    )
