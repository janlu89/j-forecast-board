"""Minimal MCP server (stdio, JSON-RPC 2.0) that exposes the demo's forecasting tools to the Claude CLI.

Started by the chat endpoint (chat.py) for each question; standard library only.
Every tool calls the running demo API (FORECASTER_URL) with a per-process internal token, so the model,
data and cached results already loaded in the web app are reused. Charts are written as JSON files to
FORECASTER_RUN_DIR; the chat endpoint streams them to the page. Claude only sees compact text summaries.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("FORECASTER_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("FORECASTER_TOKEN", "")
RUN_DIR = os.environ.get("FORECASTER_RUN_DIR", "")
MODELS = {"Timestral-5M": "mistralai/Timestral-5M", "Timestral-28M": "mistralai/Timestral-28M",
          "Timestral-123M": "mistralai/Timestral-123M", "Timestral-209M": "mistralai/Timestral-209M"}
_charts = 0
_ids: dict[str, list[str]] = {}


class ToolError(Exception):
    pass


# ----------------------------------------------------------------------------- demo API
def api(path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{URL}/{path}", data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json", "X-Internal-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            out = json.loads(e.read())
        except Exception:
            raise ToolError(f"HTTP {e.code}") from None
    if isinstance(out, dict) and out.get("error"):
        raise ToolError(out["error"])
    return out


def chart(kind: str, title: str, data: dict):
    global _charts
    if not RUN_DIR:
        return
    _charts += 1
    with open(os.path.join(RUN_DIR, f"chart_{_charts:03d}.json"), "w", encoding="utf-8") as f:
        json.dump(dict(kind=kind, title=title, data=data), f)


def datasets() -> list[dict]:
    ds = api("api/datasets")
    for d in ds:
        _ids[d["key"]] = d["ids"]
    return ds


def dataset_key(name: str) -> str:
    ds = datasets()
    keys = {d["key"]: d["key"] for d in ds} | {d["name"].lower(): d["key"] for d in ds}
    k = keys.get(name) or keys.get(name.lower())
    if not k:
        k = next((d["key"] for d in ds if name.lower() in d["name"].lower() or name.lower() in d["key"]), None)
    if not k:
        raise ToolError(f"Unknown dataset '{name}'. Available: {', '.join(d['key'] for d in ds)}")
    return k


def series_index(key: str, series) -> int:
    ids = _ids.get(key) or (datasets() and _ids[key])
    if series is None or series == "":
        return 0
    s = str(series).strip().lstrip("#")
    if s in ids:
        return ids.index(s)
    raise ToolError(f"Series '{series}' not found in {key}. It has {len(ids)} series with ids like {', '.join(ids[:5])}.")


def variant(model: str | None) -> str | None:
    if not model:
        return None
    repo = MODELS.get(model)
    if not repo:
        raise ToolError(f"Unknown model '{model}'. Use one of: {', '.join(MODELS)}")
    return f"{repo}|cov|missing"


def pct(x, d=1):
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def num(x, d=1):
    if x is None:
        return "n/a"
    return f"{x:,.0f}" if abs(x) >= 1000 else f"{x:,.{d}f}"


# ----------------------------------------------------------------------------- tools
def t_list_datasets(_):
    lines = []
    for d in datasets():
        cov = ", ".join(c["name"] for c in d["covariates"]) or "none"
        lines.append(f"- {d['key']}: {d['name']} | {d['n']} series ({d['id_label']} ids e.g. {', '.join(d['ids'][:3])}) | "
                     f"freq {d['freq']}, {d['start']} → {d['end']} | unit {d['unit']} | default horizon {d['horizon']} | "
                     f"covariates: {cov}\n  {d['description']}")
    return "\n".join(lines)


def t_accuracy_summary(a):
    key = dataset_key(a["dataset"])
    o = api("api/overview", dict(dataset=key))
    P = o["primary"]
    lines = [f"Dataset {o['meta']['name']}: holdout {o['holdout'][0]['start']} → {o['holdout'][-1]['end']} "
             f"({o['windows']} window(s) × {o['H']} steps, {o['scored_points']:,} points scored, never seen by the model).",
             f"Primary metric: {P}. Leaderboard (lower is better):"]
    for r in o["leaderboard"][:8]:
        lines.append(f"- {r['name']} [{r['kind']}]: {P} {r.get(P)!s:.6} | WAPE {pct(r.get('wape'))} | MAPE {pct(r.get('mape'))} | "
                     f"bias {pct(r.get('bias'))} | 80% band coverage {pct(r.get('coverage'))}")
    if o.get("kpi"):
        k = o["kpi"]
        lines.append(f"Best Timestral vs best classic method ({o['best_baseline']}): {pct(k.get('gain'))} lower {P}. "
                     f"Compute time for the whole backtest on CPU: {num(k.get('secs_total'))} s.")
    if o.get("total_kpi") is not None:
        lines.append(f"Error on the sum of all series (bottom-up): MAPE {pct(o['total_kpi'], 2)}.")
    if o.get("best_series"):
        lines.append("Easiest series: " + ", ".join(f"{x['id']} ({P} {x['model']:.3f})" for x in o["best_series"][:3]))
        lines.append("Hardest series: " + ", ".join(f"{x['id']} ({P} {x['model']:.3f})" for x in o["worst_series"][:3]))
    lb = o["leaderboard"][:8]
    chart("leaderboard", f"{o['meta']['name']} · {P.upper()} on the holdout (lower is better)",
          dict(metric=P, names=[r["name"] for r in lb], values=[r.get(P) for r in lb], kinds=[r["kind"] for r in lb]))
    return "\n".join(lines)


def t_forecast(a):
    key = dataset_key(a["dataset"])
    s = series_index(key, a.get("series"))
    body = dict(dataset=key, series=s, horizon=a.get("horizon"), origin=a.get("from_date"), variant=variant(a.get("model")))
    r = api("api/live", body)
    f = r["forecast"]
    n = len(r["fdates"])
    tot = sum(x for x in f["median"] if x is not None)
    lines = [f"{r['model']} forecast for {r['meta']['id_label']} {r['id']} of {r['meta']['name']} from {r['origin']}, "
             f"{n} steps ({r['fdates'][0]} → {r['fdates'][-1]}), unit {r['meta']['unit']}, computed in {num(r['seconds'], 2)} s on CPU.",
             f"Sum of the median over the horizon: {num(tot)}; P10–P90 = 80% band.", "step | date | median | P10 | P90"]
    step = max(1, n // 14)
    for i in range(0, n, step):
        lines.append(f"{i} | {r['fdates'][i]} | {num(f['median'][i])} | {num(f['lo'][i])} | {num(f['hi'][i])}")
    m = r.get("metrics") or {}
    if m:
        lines.append(f"The real values are known for this period: MAPE {pct(m.get('mape'))}, WAPE {pct(m.get('wape'))}, "
                     f"bias {pct(m.get('bias'))}, coverage of the 80% band {pct(m.get('coverage'), 0)}.")
    else:
        lines.append("This is a true forecast of the future: reality is not known yet.")
    chart("forecast", f"{r['meta']['id_label']} {r['id']} · {r['meta']['name']} · forecast from {r['origin']}", r)
    return "\n".join(lines)


def t_rank_series(a):
    key = dataset_key(a["dataset"])
    prim = next(d for d in datasets() if d["key"] == key)["primary"]
    r = api("api/ranking", dict(dataset=key, variant=variant(a.get("model"))))
    r = [x for x in r if x["err"] is not None]
    n = max(1, min(int(a.get("n") or 5), 20))
    which = a.get("which", "worst")
    r.sort(key=lambda x: x["err"], reverse=which == "worst")
    fmt = (lambda v: pct(v)) if prim in ("mape", "wape", "smape", "rmspe") else (lambda v: f"{v:.3f}")
    meaning = {"mape": "MAPE = average % error per point", "wape": "WAPE = total error / total volume",
               "mase": "MASE = error relative to the seasonal-naive rule, below 1 is better"}.get(prim, prim.upper())
    return (f"{which.capitalize()} {n} series by holdout error ({len(r)} series scored; metric {meaning}; lower is better):\n"
            + "\n".join(f"- {x['id']}: {fmt(x['err'])}" for x in r[:n]))


def t_order_plan(a):
    key = dataset_key(a["dataset"])
    s = series_index(key, a.get("series"))
    body = dict(dataset=key, series=s, scope=a.get("scope", "all"), margin=float(a.get("margin", 0.4)),
                holding=float(a.get("leftover_cost", 0.15)), target=float(a.get("target_availability", 0.95)),
                variant=variant(a.get("model")))
    r = api("api/planner", body)
    sm, c = r["same"], r["cost"]
    lines = [f"Order planner on {r['meta']['name']} ({'all series' if r['scope'] == 'all' else 'series ' + r['id']}), "
             f"holdout {r['windows'][0]['start']} → {r['windows'][-1]['end']}, {r['points']:,} {r['period']}s scored. "
             f"Assumptions: lost margin {pct(r['margin'], 0)} of value per missed sale, leftover cost {pct(r['holding'], 0)} of value.",
             f"At {pct(sm['target'], 0)} availability (fill rate): Timestral needs leftover stock = {pct(sm.get('timestral'))} of demand "
             f"(order ≈ P{round((sm.get('timestral_level') or 0) * 100)}), the classic rule '{r['baseline']}' + buffer needs "
             f"{pct(sm.get('baseline'))} (buffer ×{num(sm.get('baseline_buffer'), 2)}). Safety stock saving: {pct(sm.get('saving'))}.",
             f"Cost view (critical ratio {pct(c['ratio'], 0)} → order P{round(c['level'] * 100)}):"]
    for t in r["table"]:
        lines.append(f"- {t['name']}: fill {pct(t['fill'])}, leftover {pct(t['leftover_pct'])} of demand, cost {num(t['cost'])}")
    lines.append(f"Saving vs the classic rule with its best buffer (chosen in hindsight, so favourable to it): {num(c['saving'])} "
                 f"({pct(c.get('saving_pct'))}) in {r['meta']['unit']} over the holdout; ≈ ×{num(c['per_year'], 1)} for a year (rough extrapolation).")
    p = r["plan"]
    lines.append(f"Next {len(p['future_dates'])} {r['period']}s for series {p['id']}: expected {num(p['total_median'])}, "
                 f"suggested order {num(p['total_order'])} (P{round(c['level'] * 100)} per {r['period']}).")
    chart("planner", f"Order planner · {r['meta']['name']}", r)
    return "\n".join(lines)


def t_what_if(a):
    key = dataset_key(a["dataset"])
    s = series_index(key, a.get("series"))
    edit = dict(name=a["covariate"], mode=a.get("mode", "set"), value=float(a["value"]), start=int(a.get("start_step", 0)),
                end=a.get("end_step"))
    r = api("api/whatif", dict(dataset=key, series=s, horizon=a.get("horizon"), edits=[edit], variant=variant(a.get("model"))))
    t = r["totals"]
    names = [c["name"] for c in r["covariates"]]
    chart("whatif", f"What-if · {r['meta']['id_label']} {r['id']} · {edit['name']} {edit['mode']} {edit['value']:g}", r)
    return (f"What-if on {r['meta']['id_label']} {r['id']} of {r['meta']['name']} ({r['future_dates'][0]} → {r['future_dates'][-1]}): "
            f"{edit['name']} {edit['mode']} {edit['value']:g} on steps {edit['start']}–{edit['end'] if edit['end'] is not None else 'end'}.\n"
            f"Total median: base {num(t['base'])} → scenario {num(t['scenario'])} ({pct(t.get('pct'))}). "
            f"Known covariates available: {', '.join(names)}. Note: this is how the model reacts, not a measured causal effect.")


def t_anomalies(a):
    key = dataset_key(a["dataset"])
    s = series_index(key, a.get("series"))
    r = api("api/anomalies", dict(dataset=key, series=s, windows=int(a.get("windows", 20)), variant=variant(a.get("model"))))
    top = r["anomalies"][:8]
    return (f"Anomaly scan of {r['meta']['id_label']} {r['id']} ({r['windows']} windows × {r['step']} steps, 98% band): "
            f"{len(r['anomalies'])} points outside the band = {pct(r['rate'])} (≈{pct(r['expected_rate'], 0)} expected by chance).\n"
            + "\n".join(f"- {x['date']}: actual {num(x['actual'])}, expected {num(x['expected'])} "
                        f"(band {num(x['lo'])}–{num(x['hi'])}), {x['direction']}" for x in top))


_DS = {"type": "string", "description": "Dataset key or name, e.g. 'rossmann', 'passengers', 'energy', 'bike'."}
_SER = {"type": "string", "description": "Series id as shown in the dataset (e.g. a store number for rossmann). Default: first series."}
_MODEL = {"type": "string", "enum": list(MODELS), "description": "Model size (default Timestral-28M; 209M is slower and slightly more accurate)."}
TOOLS = {
    "list_datasets": (t_list_datasets, "List the datasets loaded in the demo with their series, frequency, dates, unit and covariates.",
                      {"type": "object", "properties": {}}),
    "accuracy_summary": (t_accuracy_summary, "How accurate is Timestral on a dataset: blind backtest on the last period vs classic methods "
                         "(leaderboard, gain, calibration, easiest/hardest series). Shows a chart.",
                         {"type": "object", "properties": {"dataset": _DS}, "required": ["dataset"]}),
    "forecast": (t_forecast, "Run Timestral now for one series: median and P10–P90 band. from_date in the past = backtest scored against reality; "
                 "omitted = true forecast of the future. Shows a chart.",
                 {"type": "object", "properties": {"dataset": _DS, "series": _SER, "horizon": {"type": "integer", "minimum": 1, "maximum": 1000},
                                                   "from_date": {"type": "string", "description": "YYYY-MM-DD; forecast as if today were this date."},
                                                   "model": _MODEL}, "required": ["dataset"]}),
    "rank_series": (t_rank_series, "Best or worst forecast series of a dataset by holdout error.",
                    {"type": "object", "properties": {"dataset": _DS, "which": {"type": "string", "enum": ["best", "worst"]},
                                                      "n": {"type": "integer", "minimum": 1, "maximum": 20}, "model": _MODEL},
                     "required": ["dataset"]}),
    "order_plan": (t_order_plan, "Turn the forecast into a stocking decision: how much leftover stock Timestral's quantiles need for a target "
                   "availability vs a classic forecast + safety buffer, the cost of lost sales vs leftovers, and the suggested order "
                   "for the next period of one series. Shows a chart.",
                   {"type": "object", "properties": {"dataset": _DS, "series": _SER,
                                                     "scope": {"type": "string", "enum": ["all", "series"], "description": "Score all series or just this one."},
                                                     "target_availability": {"type": "number", "minimum": 0.5, "maximum": 0.995, "description": "Fill rate, e.g. 0.95."},
                                                     "margin": {"type": "number", "description": "Margin lost per missed sale, share of value (default 0.4)."},
                                                     "leftover_cost": {"type": "number", "description": "Cost of a leftover unit, share of value (default 0.15)."},
                                                     "model": _MODEL}, "required": ["dataset"]}),
    "what_if": (t_what_if, "Scenario on the future of one series by editing a covariate known in advance (e.g. Promo, Open, StateHoliday "
                "for rossmann): mode set/shift/scale over forecast steps [start_step, end_step). Shows a chart.",
                {"type": "object", "properties": {"dataset": _DS, "series": _SER, "covariate": {"type": "string"},
                                                  "mode": {"type": "string", "enum": ["set", "shift", "scale"]}, "value": {"type": "number"},
                                                  "start_step": {"type": "integer", "minimum": 0}, "end_step": {"type": "integer", "minimum": 1},
                                                  "horizon": {"type": "integer", "minimum": 1, "maximum": 1000}, "model": _MODEL},
                 "required": ["dataset", "covariate", "value"]}),
    "detect_anomalies": (t_anomalies, "Find unusual points in the recent past of one series (outside the model's 98% band).",
                         {"type": "object", "properties": {"dataset": _DS, "series": _SER, "windows": {"type": "integer", "minimum": 1, "maximum": 100},
                                                           "model": _MODEL}, "required": ["dataset"]}),
}


# ----------------------------------------------------------------------------- JSON-RPC loop
def handle(msg: dict) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # notification
        return None
    if method == "initialize":
        result = dict(protocolVersion=msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                      capabilities={"tools": {}}, serverInfo={"name": "timestral-forecaster", "version": "1.0.0"})
    elif method == "tools/list":
        result = dict(tools=[dict(name=k, description=d, inputSchema=s) for k, (_, d, s) in TOOLS.items()])
    elif method == "tools/call":
        p = msg.get("params", {})
        fn = TOOLS.get(p.get("name"), (None,))[0]
        if fn is None:
            return dict(jsonrpc="2.0", id=mid, error=dict(code=-32602, message=f"Unknown tool {p.get('name')}"))
        try:
            result = dict(content=[dict(type="text", text=fn(p.get("arguments") or {}))])
        except (ToolError, KeyError, ValueError, TypeError) as e:
            result = dict(content=[dict(type="text", text=f"Error: {e}")], isError=True)
    elif method == "ping":
        result = {}
    else:
        return dict(jsonrpc="2.0", id=mid, error=dict(code=-32601, message=f"Method not found: {method}"))
    return dict(jsonrpc="2.0", id=mid, result=result)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            out = handle(json.loads(line))
        except Exception as e:  # never die on a bad message
            out = dict(jsonrpc="2.0", id=None, error=dict(code=-32603, message=str(e)))
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
