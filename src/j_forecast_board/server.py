"""Timestral web demo – local API + static UI.

Run from the project folder:
    python -m j_forecast_board serve
"""

from __future__ import annotations

import math
import os
import platform

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agents as AG
from . import auth as A
from . import chat as CH
from . import data as D
from . import engine as E
from . import evaluate as V
from . import planner as P
from .data import known_extended

STATIC = os.path.join(os.path.dirname(__file__), "static")
app = FastAPI(title="Timestral demo")
DEFAULT_MODEL = "mistralai/Timestral-28M"


# ----------------------------------------------------------------------------- access protection
# The app can be published on the internet (Tailscale Funnel): every request needs the demo login (see auth.py).
app.middleware("http")(A.middleware)


@app.get("/login")
def login_page(request: Request):
    return A.login_page(request)


@app.post("/login")
async def login_submit(request: Request):
    return await A.login_submit(request)


@app.get("/logout")
def logout():
    return A.logout()


def default_variants(ds: D.Dataset) -> list[str]:
    out = [V.variant_key(DEFAULT_MODEL, True, False)]
    if ds.covs:
        out.append(V.variant_key(DEFAULT_MODEL, False, False))
    if ds.closed is not None:
        out.append(V.variant_key(DEFAULT_MODEL, True, True))
    return out


@app.on_event("startup")
def _startup():
    D.load_builtin()
    V.start_worker()
    for ds in sorted(D.DATASETS.values(), key=lambda d: d.N):  # small datasets first
        for i, v in enumerate(default_variants(ds)):
            V.submit(ds, ds.horizon, ds.context, v, priority=1 if i == 0 else 2)


@app.exception_handler(Exception)
async def _err(_, exc: Exception):
    return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=400)


# ----------------------------------------------------------------------------- helpers
def L(a, nd=4):
    return [None if not math.isfinite(v) else round(float(v), nd) for v in np.asarray(a, dtype=float).ravel()]


def num(x):
    return None if x is None or not math.isfinite(x) else round(float(x), 6)


class Base(BaseModel):
    dataset: str
    horizon: int | None = None
    context: int | None = None


class SeriesReq(Base):
    series: int = 0
    variant: str | None = None


def resolve(r: Base):
    ds = D.get(r.dataset)
    H = int(r.horizon or ds.horizon)
    if H < 1:
        raise ValueError("Horizon must be >= 1")
    Lc = V.eff_context(ds, r.context)
    return ds, H, Lc


def norm_variant(ds: D.Dataset, v: str | None) -> str:
    v = v or default_variants(ds)[0]
    repo, cov, zero = V.parse_variant(v)
    return V.variant_key(repo, cov and bool(ds.covs), zero and ds.closed is not None)


def fmt_dates(ds, idx):
    return [V._fmt_date(ds, i) for i in idx]


# ----------------------------------------------------------------------------- catalog / jobs
@app.get("/api/datasets")
def datasets():
    return [d.meta() for d in D.DATASETS.values()]


@app.get("/api/models")
def models():
    return [dict(id=k, name=v, cached=E.model_cached(k)) for k, v in E.MODELS.items()]


@app.get("/api/system")
def system():
    info = dict(os=f"{platform.system()} {platform.release()} ({platform.version()})", cpu=platform.processor(),
                cores=os.cpu_count(), python=platform.python_version())
    try:
        import torch

        info["torch"] = torch.__version__
    except Exception:
        pass
    return info


class StatusReq(Base):
    pass


@app.post("/api/status")
def status(r: StatusReq):
    ds, H, Lc = resolve(r)
    avail = V.available(ds, H, Lc)
    variants = []
    for repo in E.MODELS:
        for cov in ([True, False] if ds.covs else [True]):
            for zero in ([False, True] if ds.closed is not None else [False]):
                v = V.variant_key(repo, cov, zero)
                job = V.JOBS.get((ds.key, H, Lc, v))
                variants.append(dict(key=v, label=V.variant_label(ds, v), done=v in avail, model=E.MODELS[repo],
                                     state="done" if v in avail else (job or {}).get("state", "idle"),
                                     progress=num((job or {}).get("done", 0) / max(1, (job or {}).get("total", 1))) if job else None,
                                     eta=num((job or {}).get("eta")) if job else None,
                                     error=(job or {}).get("error")))
    return dict(H=H, L=Lc, variants=variants, jobs=V.jobs_for(ds.key), any_running=any(j["state"] in ("running", "queued") for j in V.JOBS.values()))


class RunReq(Base):
    variant: str


@app.post("/api/run")
def run(r: RunReq):
    ds, H, Lc = resolve(r)
    j = V.submit(ds, H, Lc, norm_variant(ds, r.variant))
    return dict(state=j["state"])


# ----------------------------------------------------------------------------- analytics views
@app.post("/api/overview")
def api_overview(r: Base):
    ds, H, Lc = resolve(r)
    return V.overview(ds, H, Lc)


@app.post("/api/series")
def api_series(r: SeriesReq):
    ds, H, Lc = resolve(r)
    return V.series_view(ds, r.series, H, Lc, norm_variant(ds, r.variant))


@app.post("/api/ranking")
def api_ranking(r: SeriesReq):
    ds, H, Lc = resolve(r)
    return V.series_ranking(ds, H, Lc, norm_variant(ds, r.variant))


@app.post("/api/total")
def api_total(r: Base):
    ds, H, Lc = resolve(r)
    if ds.N < 2:
        raise ValueError("This dataset has a single series: there is no total to aggregate.")
    return V.total_view(ds, H, Lc)


# ----------------------------------------------------------------------------- on-demand forecasts
def _q3(q):
    return dict(median=L(q[:, E.qi(0.5)]), lo=L(q[:, E.qi(0.1)]), hi=L(q[:, E.qi(0.9)]))


class ReplayReq(SeriesReq):
    frames: int = 40
    span: int | None = None


@app.post("/api/replay")
def api_replay(r: ReplayReq):
    ds, H, Lc = resolve(r)
    repo, cov, zero = V.parse_variant(norm_variant(ds, r.variant))
    s, T = r.series, ds.T
    min_hist = max(3 * ds.season, 2 * H, 24)
    span = min(r.span or max(6 * H, 8 * ds.season), T - min_hist)
    if span < 1:
        raise ValueError("Series too short for a replay.")
    n = max(2, min(r.frames, span + 1, 120))
    cuts = sorted(set(int(round(c)) for c in np.linspace(T - span, T, n)))
    items = [(s, c) for c in cuts]
    q, secs = E.forecast(ds, repo, items, H, Lc, cov, zero, chunk=32)
    A = E.actuals(ds, items, H)
    M = E.eval_mask(ds, A, items, H)
    frames = []
    for k, c in enumerate(cuts):
        f = dict(cut=c, **_q3(q[k]))
        if M[k].any():
            m = E.metrics(A[k], q[k][:, E.qi(0.5)], M[k], np.full(H, E.mase_scale(ds, s, c)), q[k])
            f.update(err=num(m.get(ds.primary)), coverage=num(m.get("coverage")), seen=int(M[k].sum()))
        frames.append(f)
    return dict(meta=ds.meta(), id=ds.ids[s], horizon=H, model=V.variant_label(ds, V.variant_key(repo, cov, zero)),
                dates=fmt_dates(ds, range(T)), y=L(ds.y_display(s)), future_dates=fmt_dates(ds, range(T, T + H)),
                frames=frames, seconds=num(secs))


class LiveReq(SeriesReq):
    origin: str | None = None  # date: forecast as if today were this date (default: end of data)


@app.post("/api/live")
def api_live(r: LiveReq):
    ds, H, Lc = resolve(r)
    repo, cov, zero = V.parse_variant(norm_variant(ds, r.variant))
    s, T = r.series, ds.T
    c = T
    if r.origin:
        c = int(ds.dates.searchsorted(pd.Timestamp(r.origin), side="right"))
        c = max(min(c, T), max(2 * ds.season, 8))
    q, secs = E.forecast(ds, repo, [(s, c)], H, Lc, cov, zero)
    q = q[0]
    A = E.actuals(ds, [(s, c)], H)
    M = E.eval_mask(ds, A, [(s, c)], H)
    m = E.metrics(A[0], q[:, E.qi(0.5)], M[0], np.full(H, E.mase_scale(ds, s, c)), q) if M.any() else {}
    show = max(0, c - max(6 * H, 8 * ds.season))
    end = min(T, c + H)
    return dict(meta=ds.meta(), id=ds.ids[s], horizon=H, model=V.variant_label(ds, V.variant_key(repo, cov, zero)),
                origin=V._fmt_date(ds, c - 1), dates=fmt_dates(ds, range(show, end)), y=L(ds.y_display(s)[show:end]),
                cut_offset=c - show, fdates=fmt_dates(ds, range(c, c + H)), forecast=dict(**_q3(q), lo90=L(q[:, E.qi(0.05)]), hi90=L(q[:, E.qi(0.95)])),
                metrics={k: num(v) if k != "n" else v for k, v in m.items()}, seconds=num(secs),
                first=V._fmt_date(ds, max(2 * ds.season, 8)), last=V._fmt_date(ds, T - 1))


class SplitReq(SeriesReq):
    start: str | None = None  # first date given to the model
    split: str | None = None  # last date given to the model
    end: str | None = None  # last date to forecast


STEPS_PER_YEAR = {"h": 8760, "D": 365, "7D": 52, "MS": 12, "QS": 4}


def _split_baselines(ds: D.Dataset, y: np.ndarray, a: int, c: int, H: int) -> dict[str, np.ndarray]:
    """Classic rules that, like the model, only use the data between a and c."""
    ctx = y[a:c]

    def repeat(lag):
        out = np.full(H, np.nan)
        for i in range(H):
            j = c + i
            while j >= c:
                j -= lag
            while j >= a and not np.isfinite(y[j]):
                j -= lag
            out[i] = y[j] if j >= a else np.nan
        return out

    out = {}
    lag = {"h": 8736, "D": 364, "7D": 52, "MS": 12, "QS": 4}.get(ds.freq)
    if lag and c - a >= lag:
        out["Same period last year"] = repeat(lag)
    out[{7: "Repeat last week", 24: "Repeat last day", 12: "Repeat last year"}.get(ds.season, "Repeat last cycle")] = repeat(ds.season)
    out["Average of the given data"] = np.full(H, np.nanmean(ctx))
    for v in out.values():
        v[~np.isfinite(v)] = np.nanmean(ctx)
    return out


@app.post("/api/split")
def api_split(r: SplitReq):
    ds = D.get(r.dataset)
    repo, cov, zero = V.parse_variant(norm_variant(ds, r.variant))
    s, T, S = r.series, ds.T, ds.season
    spy = STEPS_PER_YEAR.get(ds.freq, 365)

    def at(d, default, side="left"):
        return default if not d else int(ds.dates.searchsorted(pd.Timestamp(d), side=side))

    e = min(T, at(r.end, T, "right"))
    a = max(0, at(r.start, max(0, e - 5 * spy)))
    c = min(e - 1, at(r.split, a + 2 * spy, "right"))
    if c - a < 2 * S:
        raise ValueError(f"Give the model at least {2 * S} points (two cycles).")
    H = e - c
    if H > 4000:
        raise ValueError(f"{H} steps to forecast: choose a shorter range (max 4,000 steps).")
    q, secs = E.forecast(ds, repo, [(s, c)], H, c - a, cov, zero)
    q = q[0]
    y = ds.y_display(s)
    A = ds.Y[s, c:e]
    M = E.eval_mask(ds, A[None, :], [(s, c)], H)[0]
    scale = np.full(H, _scale(ds.Y[s, a:c], S))  # MASE relative to the naive error on the data the model saw
    med = q[:, E.qi(0.5)]
    rows = [dict(name=E.MODELS[repo] + ("" if cov or not ds.covs else " · no covariates"), kind="timestral",
                 **{k: num(v) if k != "n" else v for k, v in E.metrics(A, med, M, scale, q).items()})]
    base = _split_baselines(ds, ds.Y[s], a, c, H)
    for name, p in base.items():
        if ds.closed is not None:
            p[ds.closed[s, c:e]] = 0.0
        rows.append(dict(name=name, kind="baseline", **{k: num(v) if k != "n" else v for k, v in E.metrics(A, p, M, scale).items()}))
    rows.sort(key=lambda x: x.get(ds.primary) if x.get(ds.primary) is not None else 1e9)

    # error by period (year / quarter / month of the forecast)
    fd = ds.dates[c:e]
    span_days = (fd[-1] - fd[0]).days
    code, lab = ("Y", lambda p: str(p.year)) if span_days > 540 else ("Q", lambda p: f"{p.year} Q{p.quarter}") if span_days > 120 else ("M", lambda p: p.strftime("%b %Y"))
    per = pd.PeriodIndex(fd, freq=code)
    periods = []
    for pkey in per.unique():
        m = (per == pkey)
        if not (M & m).any():
            continue
        item = dict(label=lab(pkey), steps=int(m.sum()))
        item["Timestral"] = num(E.metrics(A[m], med[m], M[m], scale[m]).get(ds.primary))
        for name, p in base.items():
            item[name] = num(E.metrics(A[m], p[m], M[m], scale[m]).get(ds.primary))
        lo, hi = q[m, E.qi(0.1)], q[m, E.qi(0.9)]
        item["width"] = num(np.nanmean(hi - lo) / max(np.nanmean(np.abs(A[m])), 1e-9))
        periods.append(item)

    # period totals (monthly for daily/hourly data, yearly for monthly data)
    tcode = "M" if ds.freq in ("h", "D", "7D") else "Y"
    tper = pd.PeriodIndex(fd, freq=tcode)
    agg = (lambda v, m: float(np.nansum(v[m]))) if ds.agg == "sum" else (lambda v, m: float(np.nanmean(v[m])))
    best_b = next(x["name"] for x in rows if x["kind"] == "baseline")
    table = []
    for pkey in tper.unique():
        m = (tper == pkey) & np.isfinite(A)
        if not m.any():
            continue
        act, fc, bl = agg(A, m), agg(med, m), agg(base[best_b], m)
        table.append(dict(period=pkey.strftime("%b %Y") if tcode == "M" else str(pkey.year), actual=num(act), forecast=num(fc),
                          lo=num(agg(q[:, E.qi(0.1)], m)), hi=num(agg(q[:, E.qi(0.9)], m)),
                          err=num((fc - act) / act) if act else None, baseline=num(bl), base_err=num((bl - act) / act) if act else None))

    # how the model did it
    k = max(1, H // 10)
    wfirst = np.nanmean(q[:k, E.qi(0.9)] - q[:k, E.qi(0.1)]) / max(np.nanmean(np.abs(med[:k])), 1e-9)
    wlast = np.nanmean(q[-k:, E.qi(0.9)] - q[-k:, E.qi(0.1)]) / max(np.nanmean(np.abs(med[-k:])), 1e-9)
    m = E.get_model(repo)
    try:
        block = int(m.per_shot_horizon_patches) * int(m.model.config.patch_size)
    except Exception:
        block = None
    how = dict(context=c - a, horizon=H, ratio=num(H / (c - a)), years_seen=num((c - a) / spy), years_forecast=num(H / spy),
               cycles=num((c - a) / S), season=S, covariates=[x.name for x in ds.covs] if cov else [],
               known=[x.name for x in ds.covs if x.kind == "known"] if cov else [], width_first=num(wfirst), width_last=num(wlast),
               block=block, blocks=int(np.ceil(H / block)) if block else None, quantiles=len(E.Q_LEVELS))
    show0 = a
    L_ = lambda v: L(v, 3)  # noqa: E731
    return dict(meta=ds.meta(), id=ds.ids[s], model=V.variant_label(ds, V.variant_key(repo, cov, zero)),
                start=V._fmt_date(ds, a), split=V._fmt_date(ds, c - 1), end=V._fmt_date(ds, e - 1),
                first=V._fmt_date(ds, 0), last=V._fmt_date(ds, T - 1),
                dates=fmt_dates(ds, range(show0, e)), y=L_(y[show0:e]), cut=c - show0,
                forecast=dict(median=L_(med), lo=L_(q[:, E.qi(0.1)]), hi=L_(q[:, E.qi(0.9)]), lo90=L_(q[:, E.qi(0.05)]), hi90=L_(q[:, E.qi(0.95)])),
                baselines={k2: L_(v) for k2, v in base.items()}, leaderboard=rows, periods=periods, table=table,
                best_baseline=best_b, how=how, seconds=num(secs), primary=ds.primary, agg=ds.agg)


def _scale(h: np.ndarray, S: int) -> float:
    d = np.abs(h[S:] - h[:-S])
    d = d[np.isfinite(d)]
    v = float(d.mean()) if len(d) else 1.0
    return v if v > 0 else 1.0


class Edit(BaseModel):
    name: str
    mode: str = "keep"
    value: float = 0
    start: int = 0
    end: int | None = None


class WhatIfReq(SeriesReq):
    edits: list[Edit] = []


@app.post("/api/whatif")
def api_whatif(r: WhatIfReq):
    ds, H, Lc = resolve(r)
    repo, _, zero = V.parse_variant(norm_variant(ds, r.variant))
    s, T = r.series, ds.T
    known = [c for c in ds.covs if c.kind == "known"]
    if not known:
        raise ValueError("This dataset has no covariates known in advance: what-if needs them.")
    base = {c.name: known_extended(ds, c, H)[0] for c in known}
    scen = {k: v.copy() for k, v in base.items()}
    for e in r.edits:
        if e.name not in scen or e.mode == "keep":
            continue
        a, b = T + max(0, e.start), T + min(H, e.end if e.end is not None else H)
        seg = scen[e.name][s, a:b]
        scen[e.name][s, a:b] = {"set": np.full_like(seg, e.value), "shift": seg + e.value, "scale": seg * e.value}.get(e.mode, seg)
    saved = ds.closed
    if ds.closed is not None and "Open" in scen:  # opening days edited -> closures follow
        ds = _with_closed(ds, s, scen["Open"][s])
    qb, s1 = E.forecast(D.get(r.dataset), repo, [(s, T)], H, Lc, True, zero)
    qs, s2 = E.forecast(ds, repo, [(s, T)], H, Lc, True, zero, overrides=scen)
    show = min(T, max(4 * H, 6 * ds.season))
    tb, ts = float(np.sum(qb[0, :, E.qi(0.5)])), float(np.sum(qs[0, :, E.qi(0.5)]))
    _ = saved
    return dict(
        meta=ds.meta(), id=ds.ids[s], horizon=H, model=E.MODELS[repo],
        dates=fmt_dates(ds, range(T - show, T)), y=L(ds.y_display(s)[-show:]), future_dates=fmt_dates(ds, range(T, T + H)),
        base=_q3(qb[0]), scenario=_q3(qs[0]),
        covariates=[dict(name=c.name, cat=c.cat, base=L(base[c.name][s, T:]), scenario=L(scen[c.name][s, T:]),
                         hist=L(c.values[s, -show:]), vmin=num(np.nanmin(c.values[s])), vmax=num(np.nanmax(c.values[s])),
                         levels=sorted({x for x in L(c.values[s], 0) if x is not None}) if c.cat else None) for c in known],
        totals=dict(base=num(tb), scenario=num(ts), delta=num(ts - tb), pct=num((ts - tb) / tb) if tb else None),
        seconds=num(s1 + s2))


def _with_closed(ds: D.Dataset, s: int, open_row: np.ndarray) -> D.Dataset:
    import copy

    d2 = copy.copy(ds)
    d2.closed = ds.closed.copy()
    T = ds.T
    n = min(d2.closed.shape[1], len(open_row)) - T
    d2.closed[s, T:T + n] = open_row[T:T + n] == 0
    return d2


class AnomReq(SeriesReq):
    step: int | None = None
    windows: int = 20
    level: float = 0.98


@app.post("/api/anomalies")
def api_anomalies(r: AnomReq):
    ds, _, Lc = resolve(r)
    repo, cov, zero = V.parse_variant(norm_variant(ds, r.variant))
    s, T = r.series, ds.T
    h = int(r.step or ds.season)
    W = max(1, min(r.windows, (T - max(3 * ds.season, 2 * h)) // h))
    cuts = [T - k * h for k in range(W, 0, -1)]
    items = [(s, c) for c in cuts]
    q, secs = E.forecast(ds, repo, items, h, Lc, cov, zero, chunk=32)
    lo_l = round((1 - r.level) / 2, 2)
    il, ih, i50 = E.qi(lo_l), E.qi(1 - lo_l), E.qi(0.5)
    med, lo, hi = q[:, :, i50].ravel(), q[:, :, il].ravel(), q[:, :, ih].ravel()
    A = E.actuals(ds, items, h)
    M = E.eval_mask(ds, A, items, h).ravel()
    act = A.ravel()
    width = np.maximum(hi - lo, 1e-9)
    with np.errstate(all="ignore"):
        score = np.where(act > hi, (act - hi) / width, np.where(act < lo, (act - lo) / width, 0.0))
    score = np.where(M, score, 0.0)
    idx = np.where(score != 0)[0]
    start = cuts[0]
    found = sorted([dict(date=V._fmt_date(ds, start + i), actual=num(act[i]), expected=num(med[i]), lo=num(lo[i]),
                         hi=num(hi[i]), score=num(score[i]), direction="above" if score[i] > 0 else "below") for i in idx],
                   key=lambda x: -abs(x["score"]))
    ctx0 = max(0, start - 4 * h)
    return dict(meta=ds.meta(), id=ds.ids[s], model=E.MODELS[repo], step=h, windows=W, level=r.level,
                dates=fmt_dates(ds, range(ctx0, T)), y=L(ds.y_display(s)[ctx0:]), offset=start - ctx0,
                median=L(med), lo=L(lo), hi=L(hi), flags=[int(i) for i in idx], anomalies=found,
                rate=num(len(idx) / max(1, M.sum())), expected_rate=num(1 - r.level), seconds=num(secs))


# ----------------------------------------------------------------------------- order planner
class PlanReq(SeriesReq):
    scope: str = "all"  # all | series
    margin: float = 0.4  # margin lost on a missed sale, share of the value
    holding: float = 0.15  # cost of a leftover unit (holding, markdown, waste), share of the value
    target: float = 0.95  # availability (fill rate) to compare the two approaches at


@app.post("/api/planner")
def api_planner(r: PlanReq):
    ds, H, Lc = resolve(r)
    return P.order_plan(ds, H, Lc, norm_variant(ds, r.variant), r.series, r.scope, r.margin, r.holding, r.target)


# ----------------------------------------------------------------------------- chat (Claude CLI + forecasting tools)
class ChatReq(BaseModel):
    message: str
    history: list[dict] = []
    context: dict = {}


@app.post("/api/chat")
async def api_chat(r: ChatReq, request: Request):
    from fastapi.responses import StreamingResponse

    port = (request.scope.get("server") or ("127.0.0.1", 8000))[1]
    return StreamingResponse(CH.stream(r.message, r.history, r.context, port), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class AgentReq(BaseModel):
    id: str
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # None or "" = keep the saved key
    clear_key: bool = False
    activate: bool = False


@app.get("/api/agents")
def api_agents():
    return AG.listing()


@app.post("/api/agents")
def api_agents_save(r: AgentReq):
    fields = dict(model=r.model, base_url=r.base_url, api_key="" if r.clear_key else (r.api_key or None))
    return AG.update(r.id, fields, r.activate)


@app.post("/api/agents/test")
def api_agents_test(r: AgentReq):
    return AG.test(r.id, dict(model=r.model, base_url=r.base_url, api_key=r.api_key))


# ----------------------------------------------------------------------------- upload
@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > 200 * 1024 * 1024:
        raise ValueError("File larger than 200 MB.")
    uid, df = D.parse_upload(raw)
    cols = list(df.columns)
    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    date_guess = next((c for c in cols if c not in numeric and D.guess_dates(df[c].head(500)).notna().mean() > 0.8), None)
    cat_guess = [c for c in numeric if df[c].dropna().nunique() <= 12 and (df[c].dropna() % 1 == 0).all()]
    id_guess = next((c for c in cols if c != date_guess and c.lower() in ("store", "id", "series", "item", "sku", "negozio",
                                                                          "punto vendita", "codice", "product", "prodotto")), None)
    head = df.head(8)
    preview = [["" if pd.isna(v) else str(v) for v in row] for row in head.astype(object).values.tolist()]
    return dict(uid=uid, name=file.filename, rows=len(df), columns=cols, numeric=numeric, date_guess=date_guess,
                cat_guess=cat_guess, id_guess=id_guess, preview=preview)


class RegisterReq(BaseModel):
    uid: str
    date_col: str
    target: str
    id_col: str | None = None
    past: list[str] = []
    known: list[str] = []
    cat: list[str] = []
    freq: str | None = None
    season: int | None = None
    horizon: int | None = None
    calendar: bool = True
    country: str | None = None
    name: str | None = None
    agg: str = "sum"


@app.post("/api/upload/register")
def api_register(r: RegisterReq):
    ds = D.register_upload(r.uid, r.date_col, r.target, r.id_col or None, r.past, r.known, r.cat, r.freq, r.season,
                           r.horizon, r.calendar, r.country or None, r.name, r.agg)
    for v in default_variants(ds)[:1]:
        V.submit(ds, ds.horizon, ds.context, v)
    return ds.meta()


# ----------------------------------------------------------------------------- static
@app.get("/manual")
def manual():
    from fastapi.responses import RedirectResponse

    return RedirectResponse("static/manual/index.html")


@app.get("/manual/en")
def manual_en():
    from fastapi.responses import RedirectResponse

    return RedirectResponse("../static/manual/en.html")


@app.get("/")
def index():
    from fastapi.responses import HTMLResponse

    # Version the app's own CSS/JS by modification time so browsers never run a stale copy after an update.
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        page = f.read()
    for name in ("style.css", "app.js"):
        v = int(os.path.getmtime(os.path.join(STATIC, name)))
        page = page.replace(f'"static/{name}"', f'"static/{name}?v={v}"')
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
