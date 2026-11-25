# SPDX-License-Identifier: Apache-2.0
"""Daily minimum temperatures in Melbourne, 1981-1990."""

from __future__ import annotations

import io

import pandas as pd

from .....domain.series import Dataset
from ..downloader import Downloader


def load(downloader: Downloader) -> Dataset:
    raw = downloader.fetch(
        "https://raw.githubusercontent.com/jbrownlee/Datasets/master/daily-min-temperatures.csv",
        "daily-min-temperatures.csv",
    )
    df = pd.read_csv(io.BytesIO(raw), parse_dates=["Date"])
    d = pd.date_range(df["Date"].min(), df["Date"].max(), freq="D")
    y = df.set_index("Date")["Temp"].reindex(d).to_numpy(float)
    return Dataset(
        "melbourne",
        "Melbourne temperature · daily, 10 years",
        "Daily minimum temperature in Melbourne (°C), 1981-1990. Strong yearly cycle plus "
        "day-to-day noise; no covariates.",
        "°C",
        "D",
        7,
        30,
        0,
        d,
        y[None, :],
        ids=["Melbourne"],
        id_label="City",
        repeat_period=365,
        year_lag=365,
        primary="mase",
        agg="mean",
        source="Australian Bureau of Meteorology (via jbrownlee/Datasets)",
        notes=[
            "Temperatures can be close to 0 °C, so MASE is the headline metric; periods are "
            "compared on averages, not sums."
        ],
    )
