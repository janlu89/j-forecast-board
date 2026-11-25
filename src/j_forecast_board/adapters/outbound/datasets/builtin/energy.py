# SPDX-License-Identifier: Apache-2.0
"""ETTh1 electricity transformer load (ETDataset, CC BY-ND 4.0)."""

from __future__ import annotations

import io

import pandas as pd

from .....domain.series import Covariate, Dataset
from ..downloader import Downloader


def load(downloader: Downloader) -> Dataset:
    raw = downloader.fetch(
        "https://raw.githubusercontent.com/zhouhaoyi/ETDataset/main/ETT-small/ETTh1.csv",
        "ETTh1.csv",
    )
    df = pd.read_csv(io.BytesIO(raw), parse_dates=["date"])
    covs = [
        Covariate(c, "past", False, df[c].to_numpy(float)[None, :])
        for c in ["HULL", "MUFL", "MULL"]
    ]
    return Dataset(
        "energy",
        "Electricity transformer · hourly load",
        "ETTh1 benchmark: high useful load (HUFL) of a power transformer, hourly, 2016-2018. "
        "Other load readings "
        "are used as past-only covariates.",
        "load (MW)",
        "h",
        24,
        168,
        2048,
        pd.DatetimeIndex(df["date"]),
        df["HUFL"].to_numpy(float)[None, :],
        ids=["HUFL"],
        id_label="Series",
        covs=covs,
        primary="mase",
        year_lag=None,
        notes=[
            "The load crosses zero, so percentage errors (MAPE) are not meaningful here: MASE is "
            "the headline metric."
        ],
        source="ETDataset (Zhou et al., 2021)",
    )
