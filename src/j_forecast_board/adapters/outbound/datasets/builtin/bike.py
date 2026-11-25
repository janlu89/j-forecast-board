# SPDX-License-Identifier: Apache-2.0
"""Capital Bikeshare daily rentals (UCI #275, CC BY 4.0)."""

from __future__ import annotations

import io
import zipfile

import pandas as pd

from .....domain.series import Covariate, Dataset
from ..downloader import Downloader
from ..holiday_calendar import CountryHolidays


def load(downloader: Downloader) -> Dataset:
    raw = downloader.fetch(
        "https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip", "bike_sharing.zip"
    )
    df = pd.read_csv(
        io.BytesIO(zipfile.ZipFile(io.BytesIO(raw)).read("day.csv")), parse_dates=["dteday"]
    )
    d = pd.DatetimeIndex(df["dteday"])
    v = lambda c, k=1.0: (df[c].to_numpy(float) * k)[None, :]  # noqa: E731
    covs = [
        Covariate("Holiday", "known", True, v("holiday"), rule="calendar:holiday"),
        Covariate("Working day", "known", True, v("workingday"), rule="calendar:workingday"),
        Covariate("Weather (1 clear … 4 storm)", "known", True, v("weathersit")),
        Covariate("Temperature °C", "known", False, v("temp", 41)),
    ]
    return Dataset(
        "bike",
        "Bike sharing · daily rentals",
        "Capital Bikeshare (Washington DC), total rentals per day, 2011-2012. Holidays, working "
        "days and weather "
        "are covariates known in advance (weather = forecast).",
        "rentals / day",
        "D",
        7,
        42,
        0,
        d,
        v("cnt"),
        ids=["DC"],
        id_label="City",
        covs=covs,
        repeat_period=364,
        year_lag=364,
        holidays=CountryHolidays("US"),
        source="UCI ML Repository #275",
        primary="wape",
        notes=[
            "Future weather is unknown: the forecast assumes the same weather as one year "
            "earlier (shown faded).",
            "A few near-empty days (e.g. Hurricane Sandy, 22 rentals) make MAPE explode, so WAPE "
            "is the headline metric.",
        ],
    )
