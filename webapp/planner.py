"""Order planner: turn the forecast's quantiles into a stocking decision and score it on the holdout.

Everything is computed from the cached backtest (no new model run), so it is instant.
Simplified newsvendor view: for every series and period we stock `order` units; demand above it is a lost
sale (lost margin), stock left over costs a share of its value (holding, markdown, waste).
  * Timestral: order = forecast quantile at the chosen level (e.g. P90).
  * Classic practice: order = best simple rule x safety buffer (e.g. +20%).
The two are compared at the same availability (fill rate), and on cost.
"""

from __future__ import annotations

import numpy as np

from . import engine as E
from . import evaluate as V
from .data import Dataset

STEPS_PER_YEAR = {"h": 8760, "D": 365, "7D": 52, "MS": 12, "QS": 4}
PERIOD_NAME = {"h": "hour", "D": "day", "7D": "week", "MS": "month", "QS": "quarter"}
BUFFERS = np.round(np.arange(0.50, 3.001, 0.02), 2)  # multipliers tried for the classic "forecast + safety buffer"


def _score(a: np.ndarray, order: np.ndarray, margin: float, holding: float) -> dict:
    short = np.maximum(a - order, 0.0)
    excess = np.maximum(order - a, 0.0)
    dem = max(float(a.sum()), 1e-9)
    return dict(fill=1 - float(short.sum()) / dem, in_stock=float(np.mean(a <= order + 1e-9)),
                lost=float(short.sum()), leftover=float(excess.sum()), leftover_pct=float(excess.sum()) / dem,
                stock=float(np.maximum(order, 0).sum()) / dem, cost=margin * float(short.sum()) + holding * float(excess.sum()))


def _at_fill(curve: list[dict], target: float, key: str) -> float | None:
    """Interpolate `key` at the given fill rate along a curve whose fill rate grows with the order size."""
    pts = sorted((c["fill"], c[key]) for c in curve)
    xs, ys = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    if target < xs[0] or target > xs[-1]:
        return None
    return float(np.interp(target, xs, ys))


def order_plan(ds: Dataset, H: int, L: int, v: str | None, series: int, scope: str = "all", margin: float = 0.4,
               holding: float = 0.15, target: float = 0.95) -> dict:
    if not (0 < margin <= 10 and 0 <= holding <= 10):
        raise ValueError("Margin must be in (0, 1000%] and leftover cost in [0, 1000%].")
    if not 0.5 <= target <= 0.995:
        raise ValueError("Target availability must be between 50% and 99.5%.")
    pn = V.panel(ds, H, L)
    trows = [r for r in pn.rows if r["kind"] == "timestral"]
    if not trows:
        raise ValueError("No Timestral results yet for this dataset: wait for the background evaluation.")
    row = next((r for r in trows if r["key"] == v), trows[0])
    brows = [r for r in pn.rows if r["kind"] == "baseline"]
    prim = ds.primary
    best_b = min(brows, key=lambda r: pn.metric_row(r).get(prim) or 1e9)

    sel = slice(None) if scope == "all" or ds.N == 1 else slice(series, series + 1)
    M = pn.M[sel]
    a = pn.A[sel][M]
    if a.size == 0:
        raise ValueError("No scored points for this selection.")
    if np.nanmin(a) < 0:
        raise ValueError("The order planner needs demand-like data (no negative values).")
    Q = row["Q"][sel][M]  # (n, n_quantiles)
    pb = np.maximum(best_b["P"][sel][M], 0.0)

    levels = [lv for lv in E.Q_LEVELS if lv >= 0.3]
    t_curve = [dict(level=lv, **_score(a, Q[:, E.qi(lv)], margin, holding)) for lv in levels]
    b_curve = [dict(buffer=float(k), **_score(a, pb * k, margin, holding)) for k in BUFFERS]

    # 1) same availability: how much leftover stock does each approach need?
    same = dict(target=target, timestral=_at_fill(t_curve, target, "leftover_pct"),
                baseline=_at_fill(b_curve, target, "leftover_pct"),
                timestral_level=_at_fill(t_curve, target, "level"), baseline_buffer=_at_fill(b_curve, target, "buffer"))
    if same["timestral"] is not None and same["baseline"]:
        same["saving"] = 1 - same["timestral"] / same["baseline"]

    # 2) cost: Timestral at the textbook quantile (no tuning) vs the classic rule with its best buffer in hindsight
    ratio = margin / (margin + holding)  # newsvendor critical ratio
    lv_opt = E.Q_LEVELS[E.qi(ratio)]
    t_opt = dict(name=f"Timestral · order P{round(lv_opt * 100)} (critical ratio {ratio:.0%})", kind="timestral",
                 **_score(a, Q[:, E.qi(lv_opt)], margin, holding))
    t_med = dict(name="Timestral · order the median (no buffer)", kind="timestral", **_score(a, Q[:, E.qi(0.5)], margin, holding))
    b_best = min(b_curve, key=lambda c: c["cost"])
    b_opt = dict(name=f"{best_b['name']} × {b_best['buffer']:.2f} (best buffer, tuned in hindsight)", kind="baseline",
                 **{k: b_best[k] for k in b_best if k != "buffer"})
    b_raw = dict(name=f"{best_b['name']} (no buffer)", kind="baseline", **_score(a, pb, margin, holding))
    table = sorted([t_opt, t_med, b_opt, b_raw], key=lambda r: r["cost"])
    periods = pn.A.shape[1] * pn.A.shape[2]  # windows x horizon steps scored per series
    per_year = STEPS_PER_YEAR.get(ds.freq, 365) / periods
    cost = dict(ratio=ratio, level=lv_opt, timestral=t_opt["cost"], baseline=b_opt["cost"],
                saving=b_opt["cost"] - t_opt["cost"], saving_pct=1 - t_opt["cost"] / b_opt["cost"] if b_opt["cost"] else None,
                per_year=per_year, demand=float(a.sum()))

    # 3) what to order next, for the selected series
    s = series
    f = row["res"]["fut"][s]
    show = min(ds.T, max(3 * H, 4 * ds.season))
    plan = dict(id=ds.ids[s], dates=[V._fmt_date(ds, i) for i in range(ds.T - show, ds.T)],
                y=[V._num(x, 2) for x in ds.y_display(s)[-show:]],
                future_dates=[V._fmt_date(ds, ds.T + i) for i in range(H)],
                median=[V._num(x, 2) for x in f[:, E.qi(0.5)]], order=[V._num(x, 2) for x in f[:, E.qi(lv_opt)]],
                lo=[V._num(x, 2) for x in f[:, E.qi(0.1)]], hi=[V._num(x, 2) for x in f[:, E.qi(0.9)]])
    plan["total_median"] = V._num(float(np.nansum(f[:, E.qi(0.5)])), 1)
    plan["total_order"] = V._num(float(np.nansum(f[:, E.qi(lv_opt)])), 1)

    clean = lambda rows: [V._clean(r) for r in rows]  # noqa: E731
    return dict(meta=ds.meta(), model=row["name"], baseline=best_b["name"], scope="all" if sel == slice(None) else "series",
                id=ds.ids[s], points=int(a.size), period=PERIOD_NAME.get(ds.freq, "period"), margin=margin, holding=holding,
                windows=[dict(start=V._fmt_date(ds, c), end=V._fmt_date(ds, c + H - 1)) for c in pn.cuts],
                timestral_curve=clean(t_curve), baseline_curve=clean(b_curve[::3]), same=V._clean(same), cost=V._clean(cost),
                table=clean(table), plan=plan)
