"""Datasets for the Timestral web demo.

A dataset is a *panel*: N series on a common date grid (N = 1 for single series).
Public datasets are downloaded once and cached in ../data.
"""

from __future__ import annotations

import io
import os
import threading
import time
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]  # the source checkout
# Folder for runtime files (datasets, results, credentials, agent settings). JFB_HOME moves it, e.g. for tests.
HOME = Path(os.environ.get("JFB_HOME") or ROOT)
DATA_DIR = HOME / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Cov:
    name: str
    kind: str  # "past" (known up to today) | "known" (known in advance, also over the future)
    cat: bool  # categorical codes vs numeric
    values: np.ndarray  # (N, T)
    future: np.ndarray | None = None  # (N, F) explicitly provided future values (NaN = unknown)
    rule: str = "repeat"  # how to fill unknown future values: "calendar:<fn>" | "repeat" | "zero"


@dataclass
class Dataset:
    key: str
    name: str
    description: str
    unit: str
    freq: str
    season: int
    horizon: int
    context: int  # default context length (0 = all)
    dates: pd.DatetimeIndex
    Y: np.ndarray  # (N, T) target, NaN = missing
    ids: list[str] = field(default_factory=lambda: ["series"])
    id_label: str = "Series"
    attrs: dict[str, list] = field(default_factory=dict)  # per-series attributes
    covs: list[Cov] = field(default_factory=list)
    closed: np.ndarray | None = None  # (N, T + F) True = known closure (forecast forced to 0, not scored)
    positive_only: bool = False  # score only points with actual > 0 (Kaggle Rossmann rule)
    primary: str = "mape"  # headline metric
    kaggle: bool = False  # show RMSPE as in the Kaggle competition
    repeat_period: int | None = None
    holiday_country: str | None = None
    year_lag: int | None = None  # lag for the "same period last year" baseline
    promo_baseline: str | None = None  # name of a known covariate for the weekday x promo baseline
    notes: list[str] = field(default_factory=list)
    source: str = ""
    persist: bool = True  # cache evaluation results on disk
    agg: str = "sum"  # how to aggregate over periods: "sum" (sales, energy) or "mean" (temperatures, prices)

    @property
    def N(self):
        return self.Y.shape[0]

    @property
    def T(self):
        return self.Y.shape[1]

    def future_dates(self, H: int) -> pd.DatetimeIndex:
        return pd.date_range(self.dates[-1], periods=H + 1, freq=self.freq)[1:]

    def y_display(self, s: int) -> np.ndarray:
        """Target as a person would read it: known closures shown as 0."""
        y = self.Y[s].copy()
        if self.closed is not None:
            y[self.closed[s, : self.T] & np.isnan(y)] = 0.0
        return y

    def meta(self):
        return dict(
            key=self.key, name=self.name, description=self.description, unit=self.unit, freq=self.freq,
            season=self.season, horizon=self.horizon, context=self.context, n=self.N, points=self.T,
            start=str(self.dates[0].date()) if self.freq != "h" else str(self.dates[0]),
            end=str(self.dates[-1].date()) if self.freq != "h" else str(self.dates[-1]),
            ids=self.ids, id_label=self.id_label, attrs=list(self.attrs), source=self.source,
            covariates=[dict(name=c.name, kind=c.kind, cat=c.cat) for c in self.covs],
            has_known=any(c.kind == "known" for c in self.covs), has_closed=self.closed is not None,
            primary=self.primary, notes=self.notes, agg=self.agg,
        )


DATASETS: dict[str, Dataset] = {}
_lock = threading.Lock()


# ----------------------------------------------------------------------------- helpers
def download(url: str, fname: str) -> bytes:
    path = DATA_DIR / fname
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for _ in range(5):
        try:
            b = urllib.request.urlopen(url, timeout=120).read()
            path.write_bytes(b)
            return b
        except Exception as e:
            last = e
            time.sleep(2)
    raise RuntimeError(f"Download failed for {url}: {last}")


def holiday_flags(dates: pd.DatetimeIndex, country: str | None) -> np.ndarray:
    if not country:
        return np.zeros(len(dates))
    import holidays

    cal = holidays.country_holidays(country, years=sorted(set(dates.year)))
    return np.array([1.0 if d.date() in cal else 0.0 for d in dates])


def calendar_values(rule: str, dates: pd.DatetimeIndex, country: str | None) -> np.ndarray:
    fn = rule.split(":", 1)[1]
    if fn == "weekday":
        return dates.dayofweek.to_numpy(float)
    if fn == "hour":
        return dates.hour.to_numpy(float)
    if fn == "month":
        return dates.month.to_numpy(float)
    hol = holiday_flags(dates, country)
    if fn == "holiday":
        return hol
    if fn == "workingday":
        return ((dates.dayofweek < 5) & (hol == 0)).astype(float)
    raise ValueError(rule)


def known_extended(ds: Dataset, cov: Cov, H: int) -> tuple[np.ndarray, np.ndarray]:
    """(N, T + H) values over history + future, and (N, H) flags: 1 = assumed (not provided)."""
    N, T = ds.N, ds.T
    fut = np.full((N, H), np.nan)
    if cov.future is not None:
        n = min(H, cov.future.shape[1])
        fut[:, :n] = cov.future[:, :n]
    miss = ~np.isfinite(fut)
    assumed = miss.astype(float)
    if miss.any():
        if cov.rule.startswith("calendar:"):
            cal = calendar_values(cov.rule, ds.future_dates(H), ds.holiday_country)
            fut = np.where(miss, cal[None, :], fut)
            assumed[:] = 0  # calendar values are known exactly
        elif cov.rule == "zero":
            fut = np.where(miss, 0.0, fut)
        else:  # same period one cycle back (e.g. same weekday last year)
            p = ds.repeat_period if ds.repeat_period and ds.repeat_period < T else ds.season
            for i in range(H):
                j = T + i
                while j >= T:
                    j -= p
                col = cov.values[:, j] if j >= 0 else np.full(N, np.nan)
                fill = np.where(np.isfinite(col), col, _last_finite(cov.values))
                fut[:, i] = np.where(miss[:, i], fill, fut[:, i])
    return np.concatenate([cov.values, fut], axis=1), assumed


def _last_finite(a: np.ndarray) -> np.ndarray:
    out = np.zeros(a.shape[0])
    for i in range(a.shape[0]):
        f = a[i][np.isfinite(a[i])]
        out[i] = f[-1] if len(f) else 0.0
    return out


# ----------------------------------------------------------------------------- built-in datasets
def load_rossmann() -> Dataset:
    base = "https://raw.githubusercontent.com/RPI-DATA/tutorials-intro/master/rossmann-store-sales/rossmann-store-sales/"
    tr = pd.read_csv(io.BytesIO(download(base + "train.csv", "rossmann/train.csv")), parse_dates=["Date"],
                     dtype={"StateHoliday": str})
    te = pd.read_csv(io.BytesIO(download(base + "test.csv", "rossmann/test.csv")), parse_dates=["Date"],
                     dtype={"StateHoliday": str})
    st = pd.read_csv(io.BytesIO(download(base + "store.csv", "rossmann/store.csv")))
    stores = np.sort(st["Store"].unique())
    dates = pd.date_range(tr["Date"].min(), tr["Date"].max(), freq="D")
    fdates = pd.date_range(dates[-1] + pd.Timedelta(days=1), te["Date"].max(), freq="D")
    N, T, F = len(stores), len(dates), len(fdates)

    def grid(df, col, idx):
        return df.pivot_table(index="Store", columns="Date", values=col, aggfunc="first").reindex(
            index=stores, columns=idx).to_numpy(float)

    tr["StateHoliday"] = (tr["StateHoliday"].fillna("0") != "0").astype(float)
    te["StateHoliday"] = (te["StateHoliday"].fillna("0") != "0").astype(float)
    sales = grid(tr, "Sales", dates)
    open_ = grid(tr, "Open", dates)
    covh = {c: grid(tr, c, dates) for c in ("Promo", "StateHoliday", "SchoolHoliday")}
    covf = {c: grid(te, c, fdates) for c in ("Open", "Promo", "StateHoliday", "SchoolHoliday")}
    in_test = np.isfinite(covf["Promo"]).any(axis=1)
    # stores missing from test.csv: promo and state holidays follow the chain-wide calendar (per-date mode),
    # school holidays repeat last year, opening follows each store's usual weekday pattern
    for c in ("Promo", "StateHoliday"):
        mode = np.nan_to_num(np.round(np.nanmean(covf[c], axis=0)))
        covf[c] = np.where(np.isfinite(covf[c]), covf[c], mode[None, :])
    school_ly = covh["SchoolHoliday"][:, T - 364:T - 364 + F]
    covf["SchoolHoliday"] = np.where(np.isfinite(covf["SchoolHoliday"]), covf["SchoolHoliday"], school_ly)
    dow_hist = dates.dayofweek.to_numpy()
    recent = slice(T - 56, T)
    usual_open = np.zeros((N, 7))
    for d in range(7):
        m = dow_hist[recent] == d
        usual_open[:, d] = np.nanmean(open_[:, recent][:, m], axis=1)
    fdow = fdates.dayofweek.to_numpy()
    est_open = (usual_open[:, fdow] >= 0.5) & (covf["StateHoliday"] == 0)
    covf["Open"] = np.where(np.isfinite(covf["Open"]), covf["Open"], np.where(in_test[:, None], 1.0, est_open))

    # Promo2: continuous promotion in given months since a given ISO week
    months = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6, "Jul": 7, "Aug": 8, "Sept": 9,
              "Oct": 10, "Nov": 11, "Dec": 12}
    alld = dates.append(fdates)
    p2 = np.zeros((N, len(alld)))
    st = st.set_index("Store").reindex(stores)
    for i, (_, r) in enumerate(st.iterrows()):
        if r["Promo2"] == 1 and isinstance(r["PromoInterval"], str):
            since = pd.Timestamp.fromisocalendar(int(r["Promo2SinceYear"]), int(r["Promo2SinceWeek"]), 1)
            ms = {months[m] for m in r["PromoInterval"].split(",") if m in months}
            p2[i] = ((alld >= since) & alld.month.isin(list(ms))).astype(float)

    closed_hist = open_ == 0
    Y = np.where(closed_hist, np.nan, sales)  # the trick: closed days are missing data, not zero sales
    closed = np.concatenate([closed_hist, covf["Open"] == 0], axis=1)
    covs = [
        Cov("School holiday", "known", True, covh["SchoolHoliday"], future=covf["SchoolHoliday"]),
        Cov("Public holiday", "known", True, covh["StateHoliday"], future=covf["StateHoliday"]),
        Cov("Promo2 active", "known", True, p2[:, :T], future=p2[:, T:]),
        Cov("Promo", "known", True, covh["Promo"], future=covf["Promo"]),
        Cov("Open", "known", True, np.nan_to_num(open_, nan=1.0), future=covf["Open"]),
    ]
    attrs = {
        "Store type": st["StoreType"].astype(str).tolist(),
        "Assortment": st["Assortment"].map({"a": "basic", "b": "extra", "c": "extended"}).fillna("?").tolist(),
        "Competitor (m)": st["CompetitionDistance"].fillna(-1).astype(int).tolist(),
        "Promo2": st["Promo2"].map({1: "yes", 0: "no"}).tolist(),
    }
    missing_stores = int((~in_test).sum())
    return Dataset(
        "rossmann", "Rossmann store sales · 1,115 stores",
        "Daily sales of 1,115 Rossmann drugstores in Germany, 2013-01-01 → 2015-07-31 (Kaggle competition data). "
        "Opening days, promotions, Promo2, school and public holidays are known in advance.",
        "daily sales €", "D", 7, 48, 512, dates, Y, ids=[str(s) for s in stores], id_label="Store", attrs=attrs,
        covs=covs, closed=closed, positive_only=True, primary="mape", kaggle=True, repeat_period=364, year_lag=364,
        promo_baseline="Promo",
        notes=[f"Future covariates come from test.csv; for {missing_stores} stores not in that file promotions, "
               "holidays and opening days are estimated.",
               "180 stores have no data in the second half of 2014 (a hole in the dataset, not a sales drop).",
               "Closed days are treated as missing data, not as zero sales; scoring uses only days with sales > 0 "
               "(as in the Kaggle competition)."],
        source="Kaggle 'Rossmann Store Sales' (2015), public GitHub mirror RPI-DATA/tutorials-intro",
    )


def load_bike() -> Dataset:
    raw = download("https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip", "bike_sharing.zip")
    df = pd.read_csv(io.BytesIO(zipfile.ZipFile(io.BytesIO(raw)).read("day.csv")), parse_dates=["dteday"])
    d = pd.DatetimeIndex(df["dteday"])
    v = lambda c, k=1.0: (df[c].to_numpy(float) * k)[None, :]  # noqa: E731
    covs = [
        Cov("Holiday", "known", True, v("holiday"), rule="calendar:holiday"),
        Cov("Working day", "known", True, v("workingday"), rule="calendar:workingday"),
        Cov("Weather (1 clear … 4 storm)", "known", True, v("weathersit")),
        Cov("Temperature °C", "known", False, v("temp", 41)),
    ]
    return Dataset(
        "bike", "Bike sharing · daily rentals",
        "Capital Bikeshare (Washington DC), total rentals per day, 2011-2012. Holidays, working days and weather "
        "are covariates known in advance (weather = forecast).",
        "rentals / day", "D", 7, 42, 0, d, v("cnt"), ids=["DC"], id_label="City", covs=covs, repeat_period=364,
        year_lag=364, holiday_country="US", source="UCI ML Repository #275", primary="wape",
        notes=["Future weather is unknown: the forecast assumes the same weather as one year earlier (shown faded).",
               "A few near-empty days (e.g. Hurricane Sandy, 22 rentals) make MAPE explode, so WAPE is the headline metric."],
    )


def load_energy() -> Dataset:
    raw = download("https://raw.githubusercontent.com/zhouhaoyi/ETDataset/main/ETT-small/ETTh1.csv", "ETTh1.csv")
    df = pd.read_csv(io.BytesIO(raw), parse_dates=["date"])
    covs = [Cov(c, "past", False, df[c].to_numpy(float)[None, :]) for c in ["HULL", "MUFL", "MULL"]]
    return Dataset(
        "energy", "Electricity transformer · hourly load",
        "ETTh1 benchmark: high useful load (HUFL) of a power transformer, hourly, 2016-2018. Other load readings "
        "are used as past-only covariates.",
        "load (MW)", "h", 24, 168, 2048, pd.DatetimeIndex(df["date"]), df["HUFL"].to_numpy(float)[None, :],
        ids=["HUFL"], id_label="Series", covs=covs, primary="mase", year_lag=None,
        notes=["The load crosses zero, so percentage errors (MAPE) are not meaningful here: MASE is the headline metric."],
        source="ETDataset (Zhou et al., 2021)",
    )


def load_passengers() -> Dataset:
    raw = download("https://raw.githubusercontent.com/jbrownlee/Datasets/master/airline-passengers.csv",
                   "airline-passengers.csv")
    df = pd.read_csv(io.BytesIO(raw), parse_dates=["Month"])
    return Dataset(
        "passengers", "Airline passengers · monthly",
        "Classic Box-Jenkins series: international airline passengers per month (thousands), 1949-1960. Strong trend "
        "and growing seasonality, no covariates.",
        "thousand passengers", "MS", 12, 12, 0, pd.DatetimeIndex(df["Month"]), df["Passengers"].to_numpy(float)[None, :],
        ids=["World"], id_label="Series", year_lag=12, source="Box & Jenkins (1976)",
    )


def load_germany_power() -> Dataset:
    raw = download("https://raw.githubusercontent.com/jenfly/opsd/master/opsd_germany_daily.csv", "opsd_germany_daily.csv")
    df = pd.read_csv(io.BytesIO(raw), parse_dates=["Date"])
    d = pd.DatetimeIndex(df["Date"])
    covs = [Cov("Public holiday (DE)", "known", True, holiday_flags(d, "DE")[None, :], rule="calendar:holiday")]
    return Dataset(
        "germany", "Germany electricity · daily, 12 years",
        "Total electricity consumption in Germany per day (GWh), 2006-2017, from Open Power System Data. "
        "Public holidays are a covariate known in advance. Long history: ideal for the Split test.",
        "GWh / day", "D", 7, 28, 0, d, df["Consumption"].to_numpy(float)[None, :], ids=["DE"], id_label="Country",
        covs=covs, repeat_period=364, year_lag=364, holiday_country="DE", source="Open Power System Data (OPSD)",
    )


def load_melbourne() -> Dataset:
    raw = download("https://raw.githubusercontent.com/jbrownlee/Datasets/master/daily-min-temperatures.csv",
                   "daily-min-temperatures.csv")
    df = pd.read_csv(io.BytesIO(raw), parse_dates=["Date"])
    d = pd.date_range(df["Date"].min(), df["Date"].max(), freq="D")
    y = df.set_index("Date")["Temp"].reindex(d).to_numpy(float)
    return Dataset(
        "melbourne", "Melbourne temperature · daily, 10 years",
        "Daily minimum temperature in Melbourne (°C), 1981-1990. Strong yearly cycle plus day-to-day noise; no covariates.",
        "°C", "D", 7, 30, 0, d, y[None, :], ids=["Melbourne"], id_label="City", repeat_period=365, year_lag=365,
        primary="mase", agg="mean", source="Australian Bureau of Meteorology (via jbrownlee/Datasets)",
        notes=["Temperatures can be close to 0 °C, so MASE is the headline metric; periods are compared on averages, not sums."],
    )


LOADERS = [load_rossmann, load_bike, load_energy, load_passengers, load_germany_power, load_melbourne]


def load_builtin():
    for fn in LOADERS:
        try:
            ds = fn()
            DATASETS[ds.key] = ds
            print(f"[data] {ds.key}: {ds.N} series x {ds.T} points")
        except Exception as e:  # keep the app usable if one download fails
            print(f"[warn] dataset {fn.__name__} not loaded: {e}")


def get(key: str) -> Dataset:
    if key not in DATASETS:
        raise ValueError(f"Unknown dataset {key}")
    return DATASETS[key]


# ----------------------------------------------------------------------------- uploads
_uploads: dict[str, pd.DataFrame] = {}


def parse_upload(raw: bytes) -> tuple[str, pd.DataFrame]:
    df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python")
    df.columns = [str(c).strip() for c in df.columns]
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            continue
        s = df[c].astype(str).str.strip()
        num = pd.to_numeric(s, errors="coerce")
        if s.str.contains(",").any():  # European format "1.234,5"
            alt = pd.to_numeric(s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")
            if alt.notna().sum() > num.notna().sum():
                num = alt
        nonempty = s.replace({"": np.nan, "nan": np.nan}).notna()
        if nonempty.sum() and num[nonempty].notna().mean() > 0.9:
            df[c] = num
    uid = uuid.uuid4().hex[:8]
    _uploads[uid] = df
    return uid, df


def guess_dates(s: pd.Series) -> pd.Series:
    a = pd.to_datetime(s, errors="coerce", dayfirst=False)
    b = pd.to_datetime(s, errors="coerce", dayfirst=True)
    if b.notna().sum() > a.notna().sum():
        return b
    if a.notna().sum() > b.notna().sum() or a.equals(b):
        return a
    da = a.dropna().sort_values().diff().dt.total_seconds().std()
    db = b.dropna().sort_values().diff().dt.total_seconds().std()
    return b if (db or 0) < (da or 0) else a


FREQ_SEASON = {"h": 24, "D": 7, "W": 52, "MS": 12, "QS": 4}


def register_upload(uid: str, date_col: str, target: str, id_col: str | None, past: list[str], known: list[str],
                    cat: list[str], freq: str | None, season: int | None, horizon: int | None, calendar: bool,
                    country: str | None, name: str | None, agg: str = "sum") -> Dataset:
    df = _uploads[uid].copy()
    df["__d"] = guess_dates(df[date_col])
    df = df.dropna(subset=["__d"])
    if id_col:
        df["__id"] = df[id_col].astype(str)
    else:
        df["__id"] = target
    if freq in (None, "", "auto"):
        one = df[df["__id"] == df["__id"].iloc[0]].sort_values("__d")["__d"]
        f = pd.infer_freq(one.iloc[-30:]) or pd.infer_freq(one.iloc[:30])
        if f is None:
            raise ValueError("Could not infer the frequency of the dates; choose it manually.")
        freq = {"H": "h", "D": "D", "MS": "MS", "M": "MS", "ME": "MS"}.get(f, f)
        if freq.startswith("W"):
            freq = "W"
        if freq.startswith("QS") or freq.startswith("Q"):
            freq = "QS"
    pfreq = "7D" if freq == "W" else freq
    ids = sorted(df["__id"].unique(), key=lambda x: (len(x), x))
    if len(ids) > 5000:
        raise ValueError(f"{len(ids)} series: the demo supports up to 5,000.")
    df = df.drop_duplicates(["__id", "__d"], keep="last")
    yv = pd.to_numeric(df[target], errors="coerce")
    last = df.loc[yv.notna(), "__d"].max()
    full = pd.date_range(df["__d"].min(), df["__d"].max(), freq=pfreq)
    hist_idx, fut_idx = full[full <= last], full[full > last]

    def grid(col, idx):
        p = df.pivot_table(index="__id", columns="__d", values=col, aggfunc="last") if col in df else None
        return p.reindex(index=ids, columns=idx).to_numpy(float) if p is not None else np.full((len(ids), len(idx)), np.nan)

    df[target] = yv
    Y = grid(target, hist_idx)
    if np.isnan(Y).mean() > 0.5:
        raise ValueError(f"Column '{target}' has more than 50% missing values on the date grid.")
    S = season or FREQ_SEASON.get(freq, 7)
    H = horizon or {"h": 48, "D": 28, "W": 13, "MS": 12, "QS": 4}.get(freq, S)
    covs = []
    for c in past:
        covs.append(Cov(c, "past", c in cat, grid(c, hist_idx)))
    for c in known:
        fv = grid(c, fut_idx) if len(fut_idx) else None
        covs.append(Cov(c, "known", c in cat, grid(c, hist_idx),
                        future=fv if fv is not None and np.isfinite(fv).any() else None))
    N = len(ids)
    rep = lambda a: np.repeat(a[None, :], N, axis=0)  # noqa: E731
    if calendar:
        if freq == "h":
            covs.append(Cov("Hour", "known", True, rep(hist_idx.hour.to_numpy(float)), rule="calendar:hour"))
        if freq in ("h", "D"):
            covs.append(Cov("Weekday", "known", True, rep(hist_idx.dayofweek.to_numpy(float)), rule="calendar:weekday"))
        if freq in ("D", "W", "MS"):
            covs.append(Cov("Month", "known", True, rep(hist_idx.month.to_numpy(float)), rule="calendar:month"))
    if country and freq == "D":
        covs.append(Cov(f"Holiday ({country})", "known", True, rep(holiday_flags(hist_idx, country)), rule="calendar:holiday"))
    key = f"up_{uid}"
    nice = name or f"Your data · {target}"
    ds = Dataset(key, nice, f"Uploaded CSV: '{target}'" + (f" for {N} series ('{id_col}')" if id_col else "") +
                 f", {len(hist_idx)} time steps.", target, pfreq, S, H, 0, hist_idx, Y, ids=ids,
                 id_label=id_col or "Series", covs=covs, positive_only=bool(np.nanmin(Y) >= 0),
                 primary="wape" if np.nanmin(Y) >= 0 else "mase",
                 repeat_period={"D": 364, "W": 52, "h": 168}.get(freq), holiday_country=country,
                 year_lag={"D": 364, "W": 52, "MS": 12, "QS": 4}.get(freq), source="Your CSV (local only)",
                 persist=False, agg="mean" if agg == "mean" else "sum")
    with _lock:
        DATASETS[key] = ds
    return ds
