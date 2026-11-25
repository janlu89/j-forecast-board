# SPDX-License-Identifier: Apache-2.0
"""Box-Jenkins airline passengers, 1949-1960."""

from __future__ import annotations

import io

import pandas as pd

from .....domain.series import Dataset
from ..downloader import Downloader


def load(downloader: Downloader) -> Dataset:
    raw = downloader.fetch(
        "https://raw.githubusercontent.com/jbrownlee/Datasets/master/airline-passengers.csv",
        "airline-passengers.csv",
    )
    df = pd.read_csv(io.BytesIO(raw), parse_dates=["Month"])
    return Dataset(
        "passengers",
        "Airline passengers · monthly",
        "Classic Box-Jenkins series: international airline passengers per month (thousands), "
        "1949-1960. Strong trend "
        "and growing seasonality, no covariates.",
        "thousand passengers",
        "MS",
        12,
        12,
        0,
        pd.DatetimeIndex(df["Month"]),
        df["Passengers"].to_numpy(float)[None, :],
        ids=["World"],
        id_label="Series",
        year_lag=12,
        source="Box & Jenkins (1976)",
    )
