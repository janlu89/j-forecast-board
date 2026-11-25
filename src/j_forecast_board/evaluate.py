"""Evaluation pipeline: backtest every series, forecast the future, cache results, build the analytics views."""

from __future__ import annotations

import json
import queue
import threading
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from . import engine as E
from . import paths, settings
from .data import Dataset, known_extended

RESULTS_DIR = paths.current().results_for(settings.current().model)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

MEMO: dict[tuple, dict] = {}  # (ds_key, H, L, variant) -> result
JOBS: dict[tuple, dict] = {}
_q: queue.PriorityQueue = queue.PriorityQueue()  # (priority, seq, key): user requests (0) before background (1)
_seq = iter(range(10 ** 9))


# ----------------------------------------------------------------------------- variants
def variant_key(repo: str, use_cov: bool, zero: bool) -> str:
    return f"{repo}|{'cov' if use_cov else 'nocov'}|{'zero' if zero else 'missing'}"


def parse_variant(v: str):
    repo, cov, z = v.split("|")
    return repo, cov == "cov", z == "zero"


def variant_label(ds: Dataset, v: str) -> str:
    repo, cov, zero = parse_variant(v)
    lab = E.MODELS[repo]
    if ds.covs and not cov:
        lab += " · no covariates"
    if ds.closed is not None:
        lab += " · closed = 0" if zero else " · closed = missing"
    return lab


def windows(ds: Dataset, H: int) -> list[int]:
    W = 1 if ds.N >= 20 else 6
    W = max(1, min(W, (ds.T - max(3 * ds.season, 2 * H)) // H))
    return [ds.T - k * H for k in range(W, 0, -1)]


def eff_context(ds: Dataset, L: int | None) -> int:
    return ds.context if L is None else int(L)


def _path(ds: Dataset, H: int, L: int, v: str) -> Path:
    repo, cov, zero = parse_variant(v)
    name = f"H{H}_L{L}_{E.MODELS[repo]}_{'cov' if cov else 'nocov'}_{'zero' if zero else 'missing'}.npz"
    return RESULTS_DIR / ds.key / name


def get_result(ds: Dataset, H: int, L: int, v: str) -> dict | None:
    k = (ds.key, H, L, v)
    if k in MEMO:
        return MEMO[k]
    p = _path(ds, H, L, v)
    if ds.persist and p.exists():
        z = np.load(p, allow_pickle=False)
        r = {name: z[name] for name in z.files}
        r["meta"] = json.loads(str(r["meta"]))
        if ds.N > 1 and r["meta"].get("total_v") != TOTAL_V:  # older file: refresh the cheap direct-total part
            _direct_total(ds, H, L, v, r)
            r["meta"]["total_v"] = TOTAL_V
            np.savez_compressed(p, **{**{kk: vv for kk, vv in r.items() if kk != "meta"}, "meta": json.dumps(r["meta"])})
        MEMO[k] = r
        return r
    return None


TOTAL_V = 2  # version of the direct-total forecast (2 = with aggregated known covariates)


def _direct_total(ds: Dataset, H: int, L: int, v: str, res: dict):
    repo, cov, _ = parse_variant(v)
    tot = total_series(ds)
    agg = E.aggregated_known(ds, H) if cov else None
    tq = [E.forecast_series(ds, repo, tot[:c], H, L, agg)[0] for c in windows(ds, H) + [ds.T]]
    res["total_bt"], res["total_fut"] = np.stack(tq[:-1]), tq[-1]


def available(ds: Dataset, H: int, L: int) -> list[str]:
    out = []
    for repo in E.MODELS:
        for cov in ([True, False] if ds.covs else [True]):
            for zero in ([False, True] if ds.closed is not None else [False]):
                v = variant_key(repo, cov, zero)
                if get_result(ds, H, L, v) is not None:
                    out.append(v)
    return out


# ----------------------------------------------------------------------------- jobs
def submit(ds: Dataset, H: int, L: int, v: str, priority: int = 0) -> dict:
    k = (ds.key, H, L, v)
    if get_result(ds, H, L, v) is not None:
        return dict(state="done")
    if k in JOBS and JOBS[k]["state"] == "running":
        return JOBS[k]
    if k in JOBS and JOBS[k]["state"] == "queued":
        if priority < JOBS[k]["priority"]:  # promote: the worker skips the stale lower-priority entry
            JOBS[k]["priority"] = priority
            _q.put((priority, next(_seq), k))
        return JOBS[k]
    JOBS[k] = dict(dataset=ds.key, H=H, L=L, variant=v, label=variant_label(ds, v), state="queued", done=0,
                   total=0, started=None, eta=None, error=None, series=ds.N, priority=priority)
    _q.put((priority, next(_seq), k))
    return JOBS[k]


def jobs_for(ds_key: str) -> list[dict]:
    return [dict(j) for k, j in JOBS.items() if k[0] == ds_key and j["state"] in ("queued", "running", "error")]


def _worker():
    from .data import DATASETS

    while True:
        _, _, k = _q.get()
        job = JOBS[k]
        if job["state"] != "queued":  # duplicate entry after a promotion
            _q.task_done()
            continue
        try:
            ds = DATASETS[k[0]]
            job.update(state="running", started=time.time())
            _run(ds, k[1], k[2], k[3], job)
            job.update(state="done")
        except Exception as e:
            traceback.print_exc()
            job.update(state="error", error=f"{type(e).__name__}: {e}")
        finally:
            _q.task_done()


def start_worker():
    threading.Thread(target=_worker, daemon=True, name="eval-worker").start()


def _run(ds: Dataset, H: int, L: int, v: str, job: dict):
    repo, cov, zero = parse_variant(v)
    cuts = windows(ds, H)
    items = [(s, c) for s in range(ds.N) for c in cuts] + [(s, ds.T) for s in range(ds.N)]
    job["total"] = len(items)

    def prog(done, total):
        job["done"] = done
        el = time.time() - job["started"]
        job["eta"] = el / max(done, 1) * (total - done)

    q, secs = E.forecast(ds, repo, items, H, L, cov, zero, progress=prog, chunk=32)
    nb = ds.N * len(cuts)
    bt = q[:nb].reshape(ds.N, len(cuts), H, -1)
    fut = q[nb:]
    res = dict(bt=bt, fut=fut, cuts=np.array(cuts), secs=np.array(secs * nb / len(items)),
               secs_total=np.array(secs))
    if ds.N > 1:  # direct forecast of the aggregated total, for comparison with bottom-up
        _direct_total(ds, H, L, v, res)
    res["meta"] = json.dumps(dict(variant=v, H=H, L=L, N=ds.N, created=time.strftime("%Y-%m-%d %H:%M"), total_v=TOTAL_V))
    if ds.persist:
        p = _path(ds, H, L, v)
        p.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(p, **res)
    res["meta"] = json.loads(res["meta"])
    MEMO[(ds.key, H, L, v)] = res


def total_series(ds: Dataset) -> np.ndarray:
    """Sum over all series (missing / closed = 0); NaN only where no series has data."""
    tot = np.nansum(ds.Y, axis=0)
    return np.where(np.isnan(ds.Y).all(axis=0) & (ds.closed is None), np.nan, tot)


# ----------------------------------------------------------------------------- analytics helpers
def _num(x, nd=6):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(x) else round(x, nd)


def _clean(d: dict) -> dict:
    return {k: _num(v) if isinstance(v, (float, np.floating, int, np.integer)) and k != "n" else v for k, v in d.items()}


class Panel:
    """Everything needed to score all models on one dataset / horizon / context."""

    def __init__(self, ds: Dataset, H: int, L: int):
        self.ds, self.H, self.L = ds, H, L
        self.cuts = windows(ds, H)
        self.items = [(s, c) for s in range(ds.N) for c in self.cuts]
        W = len(self.cuts)
        self.A = E.actuals(ds, self.items, H).reshape(ds.N, W, H)
        self.M = E.eval_mask(ds, self.A.reshape(-1, H), self.items, H).reshape(ds.N, W, H)
        sc = np.array([E.mase_scale(ds, s, self.cuts[0]) for s in range(ds.N)])
        self.scale = np.broadcast_to(sc[:, None, None], self.A.shape)
        self.rows: list[dict] = []  # name, kind, key, P (N,W,H), Q or None, secs
        for v in available(ds, H, L):
            r = get_result(ds, H, L, v)
            if r["bt"].shape[:3] != self.A.shape:
                continue
            self.rows.append(dict(name=variant_label(ds, v), kind="timestral", key=v,
                                  P=r["bt"][..., E.qi(0.5)], Q=r["bt"], secs=float(r["secs"]), res=r))
        for b, label in E.baselines_for(ds).items():
            P = np.stack([np.stack([E.baseline(ds, b, s, c, H) for c in self.cuts]) for s in range(ds.N)])
            self.rows.append(dict(name=label, kind="baseline", key=b, P=P, Q=None, secs=None))

    def metric_row(self, row, sel=None):
        A, P, M, S = self.A, row["P"], self.M, self.scale
        Q = row["Q"]
        if sel is not None:
            A, P, M, S = A[sel], P[sel], M[sel], S[sel]
            Q = Q[sel] if Q is not None else None
        return E.metrics(A, P, M, S, Q)

    def per_series(self, row, metric):
        out = np.full(self.ds.N, np.nan)
        for s in range(self.ds.N):
            m = E.metrics(self.A[s], row["P"][s], self.M[s], self.scale[s])
            if m and m.get(metric) is not None:
                out[s] = m[metric]
        return out


_panel_cache: dict = {}


def panel(ds: Dataset, H: int, L: int) -> Panel:
    k = (ds.key, id(ds), H, L, tuple(available(ds, H, L)))
    if k not in _panel_cache:
        _panel_cache.clear()
        _panel_cache[k] = Panel(ds, H, L)
    return _panel_cache[k]


def _fmt_date(ds, i):
    d = ds.dates[i] if i < ds.T else ds.future_dates(i - ds.T + 1)[-1]
    return str(d.date()) if ds.freq != "h" else d.strftime("%Y-%m-%d %H:%M")


# ----------------------------------------------------------------------------- overview
def overview(ds: Dataset, H: int, L: int) -> dict:
    pn = panel(ds, H, L)
    prim = ds.primary
    lb = []
    for row in pn.rows:
        m = pn.metric_row(row)
        lb.append(dict(name=row["name"], kind=row["kind"], key=row["key"], secs=_num(row["secs"]), **_clean(m)))
    key = lambda r: r.get(prim) if r.get(prim) is not None else 1e9  # noqa: E731
    lb.sort(key=key)
    trows = [r for r in pn.rows if r["kind"] == "timestral"]
    brows = [r for r in pn.rows if r["kind"] == "baseline"]
    best_t = min(trows, key=lambda r: key(next(x for x in lb if x["key"] == r["key"]))) if trows else None
    best_b = min(brows, key=lambda r: key(next(x for x in lb if x["key"] == r["key"])))
    lbk = {r["key"]: r for r in lb}

    # error by forecast step
    by_step = {}
    for row in pn.rows:
        vals = []
        for h in range(H):
            m = E.metrics(pn.A[:, :, h], row["P"][:, :, h], pn.M[:, :, h], pn.scale[:, :, h])
            vals.append(_num(m.get(prim)) if m else None)
        by_step[row["name"]] = vals

    # error by calendar position (weekday / hour / month)
    cal_name, cal_labels, cal_of = _calendar(ds)
    by_cal = {}
    idx = np.array([[[c + h for h in range(H)] for c in pn.cuts]] * ds.N)
    allidx = np.concatenate([ds.dates, ds.future_dates(H)])
    pos = cal_of(pd.DatetimeIndex(allidx[idx.ravel()])).reshape(idx.shape)
    for row in [r for r in (best_t, best_b) if r is not None]:
        vals = []
        for k in range(len(cal_labels)):
            sel = pos == k
            m = E.metrics(pn.A, row["P"], pn.M & sel, pn.scale) if (pn.M & sel).any() else {}
            vals.append(_num(m.get(prim)) if m else None)
        by_cal[row["name"]] = vals

    # calibration
    calib = {}
    for row in trows:
        a, q, M = pn.A[pn.M], row["Q"][pn.M], None
        pts = []
        for lo, hi in [(0.4, 0.6), (0.3, 0.7), (0.25, 0.75), (0.2, 0.8), (0.1, 0.9), (0.05, 0.95), (0.01, 0.99)]:
            pts.append(dict(nominal=round(hi - lo, 2), observed=_num(np.mean((a >= q[:, E.qi(lo)]) & (a <= q[:, E.qi(hi)])))))
        calib[row["name"]] = pts

    out = dict(meta=ds.meta(), H=H, L=L, primary=prim, windows=len(pn.cuts),
               holdout=[dict(start=_fmt_date(ds, c), end=_fmt_date(ds, c + H - 1)) for c in pn.cuts],
               future=dict(start=_fmt_date(ds, ds.T), end=_fmt_date(ds, ds.T + H - 1)),
               leaderboard=lb, by_step=by_step, calendar=dict(name=cal_name, labels=cal_labels, values=by_cal),
               calibration=calib, best=best_t and best_t["name"], best_baseline=best_b["name"],
               scored_points=int(pn.M.sum()))

    if best_t is not None:
        mt, mb = lbk[best_t["key"]], lbk[best_b["key"]]
        out["kpi"] = dict(model=mt, baseline=mb, gain=_num(1 - mt[prim] / mb[prim]) if mb.get(prim) else None,
                          secs_total=_num(float(best_t["res"]["secs_total"])))
    # per window (single series) / distribution, breakdown and best-worst (panels)
    if len(pn.cuts) > 1:
        out["per_window"] = dict(labels=[_fmt_date(ds, c) for c in pn.cuts], values={
            row["name"]: [_num(pn.metric_row(row, (slice(None), w)).get(prim)) for w in range(len(pn.cuts))]
            for row in pn.rows})
    if ds.N > 1 and best_t is not None:
        ps_t, ps_b = pn.per_series(best_t, prim), pn.per_series(best_b, prim)
        out["distribution"] = {best_t["name"]: [_num(x, 4) for x in ps_t], best_b["name"]: [_num(x, 4) for x in ps_b]}
        order = np.argsort(np.where(np.isfinite(ps_t), ps_t, np.inf))
        fin = [i for i in order if np.isfinite(ps_t[i])]
        mk = lambda i: dict(index=int(i), id=ds.ids[i], model=_num(ps_t[i]), baseline=_num(ps_b[i]))  # noqa: E731
        out["best_series"] = [mk(i) for i in fin[:10]]
        out["worst_series"] = [mk(i) for i in fin[::-1][:10]]
        out["breakdown"] = {}
        for an, vals in ds.attrs.items():
            groups = _groups(vals)
            if not groups:
                continue
            res = {}
            for row in [r for r in pn.rows if r["kind"] == "timestral"] + [best_b]:
                res[row["name"]] = [_num(pn.metric_row(row, np.array(g["idx"])).get("wape")) for g in groups]
            out["breakdown"][an] = dict(labels=[f"{g['label']} ({len(g['idx'])})" for g in groups], values=res)
        # total (chain) error, bottom-up
        tot = total_series(ds)
        tA = np.stack([tot[c:c + H] for c in pn.cuts])
        tM = np.isfinite(tA) & (tA > 0)
        tb = best_t["P"].sum(axis=0)
        mt_tot = E.metrics(tA, tb, tM)
        out["total_kpi"] = _num(mt_tot.get("mape"))
    return out


def _groups(vals):
    v = list(vals)
    if all(isinstance(x, (int, float, np.integer, np.floating)) for x in v):
        a = np.array(v, float)
        a = np.where(a < 0, np.nan, a)
        if np.isfinite(a).sum() < 8:
            return []
        qs = np.nanquantile(a, [0, 0.25, 0.5, 0.75, 1])
        out = []
        for i in range(4):
            lo, hi = qs[i], qs[i + 1]
            idx = [j for j in range(len(a)) if np.isfinite(a[j]) and (lo <= a[j] <= hi if i == 3 else lo <= a[j] < hi)]
            out.append(dict(label=f"{lo:,.0f}–{hi:,.0f}", idx=idx))
        return [g for g in out if g["idx"]]
    labels = sorted(set(map(str, v)))
    if len(labels) > 12:
        return []
    return [dict(label=l, idx=[j for j, x in enumerate(v) if str(x) == l]) for l in labels]


def _calendar(ds: Dataset):
    if ds.freq == "h":
        return "hour of day", [f"{h:02d}" for h in range(24)], lambda d: d.hour.to_numpy()
    if ds.freq in ("D",):
        return "weekday", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], lambda d: d.dayofweek.to_numpy()
    return "month", ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], \
        lambda d: d.month.to_numpy() - 1


# ----------------------------------------------------------------------------- series view
def series_view(ds: Dataset, s: int, H: int, L: int, v: str | None) -> dict:
    pn = panel(ds, H, L)
    prim = ds.primary
    y = ds.y_display(s)
    fd = ds.future_dates(H)
    row = next((r for r in pn.rows if r["key"] == v), None) or next((r for r in pn.rows if r["kind"] == "timestral"), None)
    brows = [r for r in pn.rows if r["kind"] == "baseline"]
    lbm = {r["key"]: pn.metric_row(r).get(prim) for r in brows}
    best_b = min(brows, key=lambda r: lbm[r["key"]] if lbm[r["key"]] is not None else 1e9)
    L5 = lambda a: [_num(x, 3) for x in a]  # noqa: E731
    out = dict(meta=ds.meta(), index=s, id=ds.ids[s], H=H, primary=prim,
               dates=[_fmt_date(ds, i) for i in range(ds.T)], y=L5(y), future_dates=[_fmt_date(ds, ds.T + i) for i in range(H)],
               attrs={k: (vals[s] if not isinstance(vals[s], (np.integer, np.floating)) else vals[s].item()) for k, vals in ds.attrs.items()},
               cuts=[int(c) for c in pn.cuts], baseline=dict(name=best_b["name"], values=[L5(best_b["P"][s, w]) for w in range(len(pn.cuts))]))
    if row is not None:
        r = row["res"]
        out["model"] = row["name"]
        out["variant"] = row["key"]
        out["holdout"] = [dict(median=L5(r["bt"][s, w, :, E.qi(0.5)]), lo=L5(r["bt"][s, w, :, E.qi(0.1)]),
                               hi=L5(r["bt"][s, w, :, E.qi(0.9)])) for w in range(len(pn.cuts))]
        f = r["fut"][s]
        out["future"] = dict(median=L5(f[:, E.qi(0.5)]), lo=L5(f[:, E.qi(0.1)]), hi=L5(f[:, E.qi(0.9)]),
                             lo90=L5(f[:, E.qi(0.05)]), hi90=L5(f[:, E.qi(0.95)]))
    table = []
    for rr in pn.rows:
        m = pn.metric_row(rr, s)
        if m:
            table.append(dict(name=rr["name"], kind=rr["kind"], key=rr["key"], **_clean(m)))
    table.sort(key=lambda x: x.get(prim) if x.get(prim) is not None else 1e9)
    out["table"] = table
    covs = []
    for c in ds.covs:
        item = dict(name=c.name, kind=c.kind, cat=c.cat, values=L5(c.values[s]))
        if c.kind == "known":
            ext, assumed = known_extended(ds, c, H)
            item.update(future=L5(ext[s, ds.T:]), assumed=[int(x) for x in assumed[s]])
        covs.append(item)
    out["covariates"] = covs
    return out


def series_ranking(ds: Dataset, H: int, L: int, v: str | None) -> list[dict]:
    pn = panel(ds, H, L)
    row = next((r for r in pn.rows if r["key"] == v), None) or next((r for r in pn.rows if r["kind"] == "timestral"), None)
    if row is None:
        return []
    ps = pn.per_series(row, ds.primary)
    return [dict(index=i, id=ds.ids[i], err=_num(ps[i], 4)) for i in range(ds.N)]


# ----------------------------------------------------------------------------- total view
def total_view(ds: Dataset, H: int, L: int) -> dict:
    pn = panel(ds, H, L)
    tot = total_series(ds)
    tA = np.stack([tot[c:c + H] for c in pn.cuts])
    tM = np.isfinite(tA) & (tA > 0)
    L5 = lambda a: [_num(x, 1) for x in a]  # noqa: E731
    out = dict(meta=ds.meta(), H=H, dates=[_fmt_date(ds, i) for i in range(ds.T)], y=L5(tot),
               future_dates=[_fmt_date(ds, ds.T + i) for i in range(H)], cuts=[int(c) for c in pn.cuts], lines=[], table=[])
    trows = [r for r in pn.rows if r["kind"] == "timestral"]
    for r in pn.rows:
        bu = r["P"].sum(axis=0)  # (W, H)
        m = E.metrics(tA, bu, tM)
        out["table"].append(dict(name=f"{r['name']} · bottom-up", kind=r["kind"], **_clean(m)))
    for r in trows:
        res = r["res"]
        if "total_bt" in res:
            m = E.metrics(tA, res["total_bt"][..., E.qi(0.5)], tM, Q=res["total_bt"])
            repo = parse_variant(r["key"])[0]
            name = f"{E.MODELS[repo]} · direct on total"
            if not any(t["name"] == name for t in out["table"]):
                out["table"].append(dict(name=name, kind="direct", **_clean(m)))
    out["table"].sort(key=lambda x: x.get("mape") if x.get("mape") is not None else 1e9)
    best = next((r for r in trows if f"{r['name']} · bottom-up" == next((t["name"] for t in out["table"] if t["kind"] == "timestral"), None)), None)
    if best is not None:
        res = best["res"]
        out["model"] = best["name"]
        out["bottom_up"] = dict(holdout=[L5(best["P"].sum(axis=0)[w]) for w in range(len(pn.cuts))],
                                future=L5(res["fut"][..., E.qi(0.5)].sum(axis=0)))
        if "total_bt" in res:
            out["direct"] = dict(holdout=[dict(median=L5(res["total_bt"][w, :, E.qi(0.5)]), lo=L5(res["total_bt"][w, :, E.qi(0.1)]),
                                               hi=L5(res["total_bt"][w, :, E.qi(0.9)])) for w in range(len(pn.cuts))],
                                 future=dict(median=L5(res["total_fut"][:, E.qi(0.5)]), lo=L5(res["total_fut"][:, E.qi(0.1)]),
                                             hi=L5(res["total_fut"][:, E.qi(0.9)])))
    return out
