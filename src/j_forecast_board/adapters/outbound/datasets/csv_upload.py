# SPDX-License-Identifier: Apache-2.0
"""Read the user's CSV with pandas and turn it into a dataset.

Implements application.uploads.TableReader.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd

from ....application.uploads import UploadSpec
from ....domain.calendar import holiday_flags
from ....domain.errors import InvalidRequest
from ....domain.series import Covariate, Dataset, Visibility
from .holiday_calendar import CountryHolidays

MAX_SERIES = 5000
PREVIEW_ROWS = 8
DATE_SAMPLE = 500
ID_NAMES = (
    "store", "id", "series", "item", "sku", "negozio", "punto vendita", "codice", "product",
    "prodotto",
)  # fmt: skip
SEASON = {"h": 24, "D": 7, "W": 52, "MS": 12, "QS": 4}
HORIZON = {"h": 48, "D": 28, "W": 13, "MS": 12, "QS": 4}
REPEAT_PERIOD = {"D": 364, "W": 52, "h": 168}
YEAR_LAG = {"D": 364, "W": 52, "MS": 12, "QS": 4}


class CsvTableReader:
    def parse(self, raw: bytes) -> pd.DataFrame:
        try:
            df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python")
        except (ValueError, pd.errors.ParserError, UnicodeDecodeError) as error:
            raise InvalidRequest(f"This file could not be read as CSV: {error}") from None
        df.columns = [str(c).strip() for c in df.columns]
        for column in df.columns:
            if not pd.api.types.is_numeric_dtype(df[column]):
                df[column] = _as_numbers_if_possible(df[column])
        return df

    def preview(self, df: pd.DataFrame) -> dict:
        columns = list(df.columns)
        numeric = [c for c in columns if pd.api.types.is_numeric_dtype(df[c])]
        date_guess = next(
            (
                c
                for c in columns
                if c not in numeric and guess_dates(df[c].head(DATE_SAMPLE)).notna().mean() > 0.8
            ),
            None,
        )
        categorical = [
            c for c in numeric if df[c].dropna().nunique() <= 12 and (df[c].dropna() % 1 == 0).all()
        ]
        id_guess = next((c for c in columns if c != date_guess and c.lower() in ID_NAMES), None)
        head = df.head(PREVIEW_ROWS)
        rows = [
            ["" if pd.isna(v) else str(v) for v in row]
            for row in head.astype(object).values.tolist()
        ]
        return dict(
            rows=len(df), columns=columns, numeric=numeric, date_guess=date_guess,
            cat_guess=categorical, id_guess=id_guess, preview=rows,
        )  # fmt: skip

    def build(self, table: pd.DataFrame, spec: UploadSpec, key: str) -> Dataset:
        df = table.copy()
        df["__d"] = guess_dates(df[spec.date_col])
        df = df.dropna(subset=["__d"])
        df["__id"] = df[spec.id_col].astype(str) if spec.id_col else spec.target
        freq = spec.freq if spec.freq not in (None, "", "auto") else _infer_frequency(df)
        grid_freq = "7D" if freq == "W" else freq
        ids = sorted(df["__id"].unique(), key=lambda x: (len(x), x))
        if len(ids) > MAX_SERIES:
            raise InvalidRequest(f"{len(ids)} series: the app supports up to 5,000.")
        df = df.drop_duplicates(["__id", "__d"], keep="last")
        target = pd.to_numeric(df[spec.target], errors="coerce")
        last = df.loc[target.notna(), "__d"].max()
        full = pd.date_range(df["__d"].min(), df["__d"].max(), freq=grid_freq)
        history, future = full[full <= last], full[full > last]
        df[spec.target] = target

        def grid(column: str, dates: pd.DatetimeIndex) -> np.ndarray:
            if column not in df:
                return np.full((len(ids), len(dates)), np.nan)
            pivot = df.pivot_table(index="__id", columns="__d", values=column, aggfunc="last")
            return pivot.reindex(index=ids, columns=dates).to_numpy(float)

        values = grid(spec.target, history)
        if np.isnan(values).mean() > 0.5:
            raise InvalidRequest(
                f"Column '{spec.target}' has more than 50% missing values on the date grid."
            )
        season = spec.season or SEASON.get(freq, 7)
        horizon = spec.horizon or HORIZON.get(freq, season)
        holidays = CountryHolidays(spec.country) if spec.country else None
        covariates = [Covariate(c, "past", c in spec.cat, grid(c, history)) for c in spec.past]
        for column in spec.known:
            future_values = grid(column, future) if len(future) else None
            given = (
                future_values
                if future_values is not None and np.isfinite(future_values).any()
                else None
            )
            covariates.append(
                Covariate(column, "known", column in spec.cat, grid(column, history), future=given)
            )
        covariates += _calendar_covariates(
            history, freq, len(ids), spec.calendar, spec.country, holidays
        )
        described = f" for {len(ids)} series ('{spec.id_col}')" if spec.id_col else ""
        return Dataset(
            key, spec.name or f"Your data · {spec.target}",
            f"Uploaded CSV: '{spec.target}'{described}, {len(history)} time steps.",
            spec.target, grid_freq, season, horizon, 0, history, values, ids=ids,
            id_label=spec.id_col or "Series", covs=covariates,
            positive_only=bool(np.nanmin(values) >= 0),
            primary="wape" if np.nanmin(values) >= 0 else "mase",
            repeat_period=REPEAT_PERIOD.get(freq), holidays=holidays, year_lag=YEAR_LAG.get(freq),
            source="Your CSV (local only)", persist=False,
            agg="mean" if spec.agg == "mean" else "sum",
            visibility=Visibility.PRIVATE,
        )  # fmt: skip


def guess_dates(values: pd.Series) -> pd.Series:
    """Parse dates month-first or day-first, whichever reads more of them (and more regularly)."""
    month_first = pd.to_datetime(values, errors="coerce", dayfirst=False)
    day_first = pd.to_datetime(values, errors="coerce", dayfirst=True)
    if day_first.notna().sum() > month_first.notna().sum():
        return day_first
    if month_first.notna().sum() > day_first.notna().sum() or month_first.equals(day_first):
        return month_first
    spread_month = month_first.dropna().sort_values().diff().dt.total_seconds().std()
    spread_day = day_first.dropna().sort_values().diff().dt.total_seconds().std()
    return day_first if (spread_day or 0) < (spread_month or 0) else month_first


def _as_numbers_if_possible(column: pd.Series) -> pd.Series:
    text = column.astype(str).str.strip()
    numbers = pd.to_numeric(text, errors="coerce")
    if text.str.contains(",").any():  # European format "1.234,5"
        european = pd.to_numeric(
            text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
            errors="coerce",
        )
        if european.notna().sum() > numbers.notna().sum():
            numbers = european
    filled = text.replace({"": np.nan, "nan": np.nan}).notna()
    if filled.sum() and numbers[filled].notna().mean() > 0.9:
        return numbers
    return column


def _infer_frequency(df: pd.DataFrame) -> str:
    first = df[df["__id"] == df["__id"].iloc[0]].sort_values("__d")["__d"]
    found = pd.infer_freq(first.iloc[-30:]) or pd.infer_freq(first.iloc[:30])
    if found is None:
        raise InvalidRequest("Could not infer the frequency of the dates; choose it manually.")
    freq = {"H": "h", "D": "D", "MS": "MS", "M": "MS", "ME": "MS"}.get(found, found)
    if freq.startswith("W"):
        return "W"
    if freq.startswith("Q"):
        return "QS"
    return freq


def _calendar_covariates(history, freq, n_series, calendar, country, holidays) -> list[Covariate]:
    def repeated(row: np.ndarray) -> np.ndarray:
        return np.repeat(row[None, :], n_series, axis=0)

    out = []
    if calendar:
        if freq == "h":
            out.append(
                Covariate(
                    "Hour",
                    "known",
                    True,
                    repeated(history.hour.to_numpy(float)),
                    rule="calendar:hour",
                )
            )
        if freq in ("h", "D"):
            weekday = history.day_of_week.to_numpy(float)
            out.append(
                Covariate("Weekday", "known", True, repeated(weekday), rule="calendar:weekday")
            )
        if freq in ("D", "W", "MS"):
            out.append(
                Covariate(
                    "Month",
                    "known",
                    True,
                    repeated(history.month.to_numpy(float)),
                    rule="calendar:month",
                )
            )
    if country and freq == "D":
        flags = repeated(holiday_flags(history, holidays))
        out.append(Covariate(f"Holiday ({country})", "known", True, flags, rule="calendar:holiday"))
    return out
