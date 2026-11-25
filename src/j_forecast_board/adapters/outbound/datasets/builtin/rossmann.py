# SPDX-License-Identifier: Apache-2.0
"""Rossmann store sales (Kaggle 2015, public GitHub mirror)."""

from __future__ import annotations

import io

import numpy as np
import pandas as pd

from .....domain.series import Covariate, Dataset
from ..downloader import Downloader


def load(downloader: Downloader) -> Dataset:
    base = (
        "https://raw.githubusercontent.com/RPI-DATA/tutorials-intro/master/"
        "rossmann-store-sales/rossmann-store-sales/"
    )
    tr = pd.read_csv(
        io.BytesIO(downloader.fetch(base + "train.csv", "rossmann/train.csv")),
        parse_dates=["Date"],
        dtype={"StateHoliday": str},
    )
    te = pd.read_csv(
        io.BytesIO(downloader.fetch(base + "test.csv", "rossmann/test.csv")),
        parse_dates=["Date"],
        dtype={"StateHoliday": str},
    )
    st = pd.read_csv(io.BytesIO(downloader.fetch(base + "store.csv", "rossmann/store.csv")))
    stores = np.sort(st["Store"].unique())
    dates = pd.date_range(tr["Date"].min(), tr["Date"].max(), freq="D")
    fdates = pd.date_range(dates[-1] + pd.Timedelta(days=1), te["Date"].max(), freq="D")
    n_stores, n_days, n_future = len(stores), len(dates), len(fdates)

    def grid(df, col, idx):
        return (
            df.pivot_table(index="Store", columns="Date", values=col, aggfunc="first")
            .reindex(index=stores, columns=idx)
            .to_numpy(float)
        )

    tr["StateHoliday"] = (tr["StateHoliday"].fillna("0") != "0").astype(float)
    te["StateHoliday"] = (te["StateHoliday"].fillna("0") != "0").astype(float)
    sales = grid(tr, "Sales", dates)
    open_ = grid(tr, "Open", dates)
    covh = {c: grid(tr, c, dates) for c in ("Promo", "StateHoliday", "SchoolHoliday")}
    covf = {c: grid(te, c, fdates) for c in ("Open", "Promo", "StateHoliday", "SchoolHoliday")}
    in_test = np.isfinite(covf["Promo"]).any(axis=1)
    # stores missing from test.csv: promo and state holidays follow the chain-wide calendar
    # (per-date mode),
    # school holidays repeat last year, opening follows each store's usual weekday pattern
    for c in ("Promo", "StateHoliday"):
        mode = np.nan_to_num(np.round(np.nanmean(covf[c], axis=0)))
        covf[c] = np.where(np.isfinite(covf[c]), covf[c], mode[None, :])
    school_ly = covh["SchoolHoliday"][:, n_days - 364 : n_days - 364 + n_future]
    covf["SchoolHoliday"] = np.where(
        np.isfinite(covf["SchoolHoliday"]), covf["SchoolHoliday"], school_ly
    )
    dow_hist = dates.day_of_week.to_numpy()
    recent = slice(n_days - 56, n_days)
    usual_open = np.zeros((n_stores, 7))
    for d in range(7):
        m = dow_hist[recent] == d
        usual_open[:, d] = np.nanmean(open_[:, recent][:, m], axis=1)
    fdow = fdates.day_of_week.to_numpy()
    est_open = (usual_open[:, fdow] >= 0.5) & (covf["StateHoliday"] == 0)
    covf["Open"] = np.where(
        np.isfinite(covf["Open"]), covf["Open"], np.where(in_test[:, None], 1.0, est_open)
    )

    # Promo2: continuous promotion in given months since a given ISO week
    months = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sept": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }
    alld = dates.append(fdates)
    p2 = np.zeros((n_stores, len(alld)))
    st = st.set_index("Store").reindex(stores)
    for i, (_, r) in enumerate(st.iterrows()):
        if r["Promo2"] == 1 and isinstance(r["PromoInterval"], str):
            since = pd.Timestamp.fromisocalendar(
                int(r["Promo2SinceYear"]), int(r["Promo2SinceWeek"]), 1
            )
            ms = {months[m] for m in r["PromoInterval"].split(",") if m in months}
            p2[i] = ((alld >= since) & alld.month.isin(list(ms))).astype(float)

    closed_hist = open_ == 0
    sales_target = np.where(
        closed_hist, np.nan, sales
    )  # the trick: closed days are missing data, not zero sales
    closed = np.concatenate([closed_hist, covf["Open"] == 0], axis=1)
    covs = [
        Covariate(
            "School holiday", "known", True, covh["SchoolHoliday"], future=covf["SchoolHoliday"]
        ),
        Covariate(
            "Public holiday", "known", True, covh["StateHoliday"], future=covf["StateHoliday"]
        ),
        Covariate("Promo2 active", "known", True, p2[:, :n_days], future=p2[:, n_days:]),
        Covariate("Promo", "known", True, covh["Promo"], future=covf["Promo"]),
        Covariate("Open", "known", True, np.nan_to_num(open_, nan=1.0), future=covf["Open"]),
    ]
    attrs = {
        "Store type": st["StoreType"].astype(str).tolist(),
        "Assortment": st["Assortment"]
        .map({"a": "basic", "b": "extra", "c": "extended"})
        .fillna("?")
        .tolist(),
        "Competitor (m)": st["CompetitionDistance"].fillna(-1).astype(int).tolist(),
        "Promo2": st["Promo2"].map({1: "yes", 0: "no"}).tolist(),
    }
    missing_stores = int((~in_test).sum())
    return Dataset(
        "rossmann",
        "Rossmann store sales · 1,115 stores",
        "Daily sales of 1,115 Rossmann drugstores in Germany, 2013-01-01 → 2015-07-31 (Kaggle "
        "competition data). "
        "Opening days, promotions, Promo2, school and public holidays are known in advance.",
        "daily sales €",
        "D",
        7,
        48,
        512,
        dates,
        sales_target,
        ids=[str(s) for s in stores],
        id_label="Store",
        attrs=attrs,
        covs=covs,
        closed=closed,
        positive_only=True,
        primary="mape",
        kaggle=True,
        repeat_period=364,
        year_lag=364,
        promo_baseline="Promo",
        notes=[
            f"Future covariates come from test.csv; for {missing_stores} stores not in that file "
            f"promotions, "
            "holidays and opening days are estimated.",
            "180 stores have no data in the second half of 2014 (a hole in the dataset, not a "
            "sales drop).",
            "Closed days are treated as missing data, not as zero sales; scoring uses only days "
            "with sales > 0 "
            "(as in the Kaggle competition).",
        ],
        source=(
            "Kaggle 'Rossmann Store Sales' (2015), public GitHub mirror RPI-DATA/tutorials-intro"
        ),
    )
