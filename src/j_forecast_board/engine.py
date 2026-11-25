"""Forecasting engine: model loading, batched inputs for panels, baselines and metrics."""

from __future__ import annotations

import os
import threading
import time
import warnings

import numpy as np

from .data import Dataset, known_extended

warnings.filterwarnings("ignore")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

MODELS = {
    "mistralai/Timestral-5M": "Timestral-5M",
    "mistralai/Timestral-28M": "Timestral-28M",
    "mistralai/Timestral-123M": "Timestral-123M",
    "mistralai/Timestral-209M": "Timestral-209M",
}
Q_LEVELS = [0.01, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85,
            0.9, 0.95, 0.99]

_models: dict[str, object] = {}
_model_lock = threading.Lock()
INFER_LOCK = threading.Lock()  # one forecast at a time on a 4-core CPU


def qi(level: float) -> int:
    return min(range(len(Q_LEVELS)), key=lambda i: abs(Q_LEVELS[i] - level))


def model_cached(repo: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(repo, "model.safetensors"), str)
    except Exception:
        return False


def get_model(repo: str):
    global Q_LEVELS
    if repo not in MODELS:
        raise ValueError(f"Unknown model {repo}")
    with _model_lock:
        if repo in _models:
            return _models[repo]
        from timestral import TimestralForecaster

        m, last = None, None
        try:
            m = TimestralForecaster.from_pretrained(repo, device="cpu", local_files_only=True)
        except Exception:
            for _ in range(10):  # the connection to huggingface.co is flaky on this network
                try:
                    m = TimestralForecaster.from_pretrained(repo, device="cpu")
                    break
                except Exception as e:
                    last = e
                    time.sleep(3)
        if m is None:
            raise RuntimeError(f"Could not download {repo} after 10 attempts: {last}")
        _models[repo] = m
        Q_LEVELS = list(m.quantile_levels)
        return m


# ----------------------------------------------------------------------------- inputs
_ext_cache: dict = {}


def known_ext(ds: Dataset, cov, H: int) -> np.ndarray:
    key = (ds.key, id(ds), cov.name, H)
    if key not in _ext_cache:
        _ext_cache[key] = known_extended(ds, cov, H)[0]
    return _ext_cache[key]


def target(ds: Dataset, zero: bool) -> np.ndarray:
    if zero and ds.closed is not None:
        return np.where(ds.closed[:, : ds.T] & np.isnan(ds.Y), 0.0, ds.Y)
    return ds.Y


def build_inputs(ds: Dataset, items: list[tuple[int, int]], H: int, L: int, use_cov: bool, zero: bool = False,
                 overrides: dict | None = None):
    """Batched inputs for forecasts of series s made at cut c (history = Y[s, :c]), left-padded to a common length."""
    Y = target(ds, zero)
    maxc = max(c for _, c in items)
    n = min(L, maxc) if L else maxc
    B = len(items)
    ctx = np.full((B, n), np.nan)
    for i, (s, c) in enumerate(items):
        a = max(0, c - n)
        ctx[i, n - (c - a):] = Y[s, a:c]
    groups = {"past_covariates": [], "known_covariates": [], "categorical_past_covariates": [],
              "categorical_known_covariates": []}
    for cov in (ds.covs if use_cov else []):
        name = ("categorical_" if cov.cat else "") + ("past_covariates" if cov.kind == "past" else "known_covariates")
        if cov.kind == "past":
            src, length = cov.values, n
        else:
            src = overrides[cov.name] if overrides and cov.name in overrides else known_ext(ds, cov, H)
            length = n + H
        rows = np.full((B, length), np.nan)
        for i, (s, c) in enumerate(items):
            a = max(0, c - n)
            seg = src[s, a:c] if cov.kind == "past" else src[s, a:c + H]
            rows[i, n - (c - a):n - (c - a) + len(seg)] = seg
        groups[name].append(rows)
    kw = {k: np.stack(v, axis=1) for k, v in groups.items() if v}
    return ctx, kw


def closed_mask(ds: Dataset, items, H: int) -> np.ndarray:
    m = np.zeros((len(items), H), bool)
    if ds.closed is None:
        return m
    for i, (s, c) in enumerate(items):
        seg = ds.closed[s, c:c + H]
        m[i, :len(seg)] = seg
    return m


def forecast(ds: Dataset, repo: str, items: list[tuple[int, int]], H: int, L: int, use_cov: bool = True,
             zero: bool = False, overrides: dict | None = None, chunk: int = 64, progress=None):
    """Quantiles (B, H, Q) for each (series, cut) item; known closures forced to 0. Returns (q, seconds)."""
    m = get_model(repo)
    out = []
    t0 = time.perf_counter()
    for i in range(0, len(items), chunk):
        part = items[i:i + chunk]
        ctx, kw = build_inputs(ds, part, H, L, use_cov, zero, overrides)
        with INFER_LOCK:
            fc = m.forecast(ctx, prediction_length=H, **kw)
        out.append(np.asarray(fc.quantiles, dtype=np.float32)[:, 0])
        if progress:
            progress(min(len(items), i + chunk), len(items))
    q = np.concatenate(out)
    cm = closed_mask(ds, items, H)
    q[cm] = 0.0
    return q, time.perf_counter() - t0


def forecast_series(ds: Dataset, repo: str, y: np.ndarray, H: int, L: int, known: np.ndarray | None = None):
    """Forecast an arbitrary single series (used for the aggregated total).

    known: optional (C, len(y) + H) numeric covariates known over history and horizon."""
    m = get_model(repo)
    ctx = y[-L:] if L else y
    kw = {}
    if known is not None:
        kw["known_covariates"] = known[None, :, len(y) - len(ctx):len(y) + H]
    t0 = time.perf_counter()
    with INFER_LOCK:
        fc = m.forecast(ctx[None, :], prediction_length=H, **kw)
    return np.asarray(fc.quantiles, dtype=np.float32)[0, 0], time.perf_counter() - t0


def aggregated_known(ds: Dataset, H: int) -> np.ndarray | None:
    """Known covariates of the total: share of series with each flag (e.g. % of stores open / on promo)."""
    rows = [np.nanmean(known_ext(ds, c, H), axis=0) for c in ds.covs if c.kind == "known"]
    return np.stack(rows) if rows else None


# ----------------------------------------------------------------------------- baselines
def _seasonal_fill(h: np.ndarray, H: int, S: int) -> np.ndarray:
    """Repeat the last cycle; missing points are taken from earlier cycles."""
    out = np.full(H, np.nan)
    n = len(h)
    for i in range(H):
        j = n - S + (i % S)
        while j >= 0 and not np.isfinite(h[j]):
            j -= S
        out[i] = h[j] if j >= 0 else np.nan
    if np.isnan(out).any():
        f = h[np.isfinite(h)]
        out[np.isnan(out)] = f[-1] if len(f) else 0.0
    return out


def baseline(ds: Dataset, name: str, s: int, c: int, H: int) -> np.ndarray:
    S = ds.season
    h = ds.Y[s, :c]
    if name == "seasonal_naive":
        p = _seasonal_fill(h, H, S)
    elif name == "seasonal_mean":
        k = max(1, min(4, c // S))
        block = h[c - k * S:c].reshape(k, S)
        with np.errstate(all="ignore"):
            mean = np.nanmean(block, axis=0)
        p = np.tile(mean, int(np.ceil(H / S)))[:H]
        bad = ~np.isfinite(p)
        if bad.any():
            p[bad] = _seasonal_fill(h, H, S)[bad]
    elif name == "annual":
        lag = ds.year_lag
        idx = np.arange(c, c + H) - lag
        p = np.where(idx >= 0, h[np.clip(idx, 0, c - 1)], np.nan)
        bad = ~np.isfinite(p)
        if bad.any():
            p[bad] = _seasonal_fill(h, H, S)[bad]
    elif name == "promo":
        cov = next(cv for cv in ds.covs if cv.name == ds.promo_baseline)
        promo = known_ext(ds, cov, H)[s]
        dow = (np.arange(c + H) + ds.dates[0].dayofweek) % 7
        a = max(0, c - 182)
        hh, dd, pp = h[a:c], dow[a:c], promo[a:c]
        p = np.full(H, np.nan)
        for i in range(H):
            t = c + i
            m = (dd == dow[t]) & (pp == promo[t]) & np.isfinite(hh)
            if not m.any():
                m = (dd == dow[t]) & np.isfinite(hh)
            p[i] = hh[m].mean() if m.any() else np.nan
        bad = ~np.isfinite(p)
        if bad.any():
            p[bad] = _seasonal_fill(h, H, S)[bad]
    else:
        raise ValueError(name)
    if ds.closed is not None:
        cm = ds.closed[s, c:c + H]
        p[:len(cm)][cm] = 0.0
    return p


def baselines_for(ds: Dataset) -> dict[str, str]:
    out = {}
    if ds.promo_baseline:
        out["promo"] = f"Mean weekday × {ds.promo_baseline.lower()}"
    out["seasonal_mean"] = "Seasonal mean (4 cycles)"
    out["seasonal_naive"] = {7: "Naive weekly (last week)", 24: "Naive daily (last day)", 12: "Naive yearly (last year)"}.get(
        ds.season, "Seasonal naive")
    if ds.year_lag and ds.year_lag != ds.season and ds.T > ds.year_lag + 2 * ds.horizon:
        out["annual"] = f"Naive annual (t−{ds.year_lag})"
    return out


# ----------------------------------------------------------------------------- metrics
def mase_scale(ds: Dataset, s: int, c: int) -> float:
    h = ds.Y[s, :c]
    S = ds.season if c > 2 * ds.season else 1
    d = np.abs(h[S:] - h[:-S])
    d = d[np.isfinite(d)]
    v = float(d.mean()) if len(d) else 1.0
    return v if v > 0 else 1.0


def metrics(A: np.ndarray, P: np.ndarray, M: np.ndarray, scale: np.ndarray | None = None,
            Q: np.ndarray | None = None) -> dict:
    """A, P, M, scale: same shape (any); Q: shape + (n_quantiles,). Scored only where M is True."""
    a, p = A[M], P[M]
    if a.size == 0:
        return {}
    e = a - p
    absa = np.abs(a)
    nz = absa > 1e-9
    with np.errstate(all="ignore"):
        out = dict(
            n=int(a.size),
            mape=float(np.mean(np.abs(e[nz]) / absa[nz])) if nz.any() else None,
            smape=float(np.mean(2 * np.abs(e) / np.maximum(np.abs(a) + np.abs(p), 1e-9))),
            rmspe=float(np.sqrt(np.mean((e[nz] / a[nz]) ** 2))) if nz.any() else None,
            wape=float(np.sum(np.abs(e)) / max(np.sum(absa), 1e-9)),
            mae=float(np.mean(np.abs(e))),
            rmse=float(np.sqrt(np.mean(e ** 2))),
            bias=float(np.sum(p - a) / max(np.sum(absa), 1e-9)),
        )
        if scale is not None:
            out["mase"] = float(np.mean(np.abs(e) / scale[M]))
        if Q is not None:
            q = Q[M]
            lo, hi = q[:, qi(0.1)], q[:, qi(0.9)]
            out["coverage"] = float(np.mean((a >= lo) & (a <= hi)))
            out["width"] = float(np.sum(hi - lo) / max(np.sum(absa), 1e-9))
            lv = np.asarray(Q_LEVELS)
            ee = a[:, None] - q
            pin = np.maximum(lv * ee, (lv - 1) * ee)
            out["wql"] = float(2 * pin.sum() / len(lv) / max(np.sum(absa), 1e-9))
    return out


def eval_mask(ds: Dataset, A: np.ndarray, items, H: int) -> np.ndarray:
    M = np.isfinite(A) & ~closed_mask(ds, items, H)
    if ds.positive_only:
        M &= A > 0
    return M


def actuals(ds: Dataset, items, H: int) -> np.ndarray:
    A = np.full((len(items), H), np.nan)
    for i, (s, c) in enumerate(items):
        seg = ds.Y[s, c:c + H]
        A[i, :len(seg)] = seg
    return A
