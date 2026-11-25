# SPDX-License-Identifier: Apache-2.0
"""The assistant's forecasting tools: one definition of names, labels, descriptions and schemas.

Every tool calls the use cases directly and answers with a compact text for the AI plus,
for some tools, a chart for the user. The data rules are enforced here too, not only in the UI:
a tool call that names a private dataset is refused for an external assistant.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ...domain.errors import DomainError, PolicyViolation
from ...domain.forecast import MODEL_REPOS
from ...domain.series import Dataset
from ..forecasts.what_if import Edit, WhatIfRequest
from ..view_model import dataset_meta, to_plain
from ..views.planner import PlanRequest

MODEL_SIZES = {name: repo for repo, name in MODEL_REPOS.items()}  # "Timestral-28M" -> repo
PRIVATE_REFUSAL = (
    "Dataset '{name}' is the user's private data: it is not sent to an external AI service. "
    "Tell the user to switch to an assistant that runs on this PC to ask about it."
)


class ToolError(DomainError):
    """A tool could not run with these arguments; the message goes back to the AI."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    label: str  # shown to the user while the tool runs
    description: str
    schema: dict


@dataclass(frozen=True)
class ToolResult:
    text: str
    chart: dict | None = None


@dataclass(frozen=True)
class ToolPermissions:
    external: bool  # the assistant sends data outside this PC
    private_data_allowed: bool = False  # policy + second confirmation


_DATASET = {"type": "string", "description": "Dataset key or name, e.g. 'rossmann', 'passengers'."}
_SERIES = {
    "type": "string",
    "description": "Series id as shown in the dataset (e.g. a store number). Default: first.",
}
_MODEL = {
    "type": "string",
    "enum": list(MODEL_SIZES),
    "description": "Model size (default Timestral-28M; 209M is slower and slightly more accurate).",
}
_HORIZON = {"type": "integer", "minimum": 1, "maximum": 1000}

SPECS = [
    ToolSpec(
        "list_datasets",
        "Looking at the datasets",
        "List the datasets loaded in the app with their series, frequency, dates, unit and "
        "covariates.",
        {"type": "object", "properties": {}},
    ),
    ToolSpec(
        "accuracy_summary",
        "Reading the backtest results",
        "How accurate the model is on a dataset: blind backtest on the last period vs classic "
        "methods (leaderboard, gain, calibration, easiest/hardest series). Shows a chart.",
        {"type": "object", "properties": {"dataset": _DATASET}, "required": ["dataset"]},
    ),
    ToolSpec(
        "forecast",
        "Running the forecast",
        "Forecast one series now: median and P10-P90 band. from_date in the past = backtest "
        "scored against reality; omitted = true forecast of the future. Shows a chart.",
        {
            "type": "object",
            "properties": {
                "dataset": _DATASET,
                "series": _SERIES,
                "horizon": _HORIZON,
                "from_date": {
                    "type": "string",
                    "description": "YYYY-MM-DD; forecast as if today were this date.",
                },
                "model": _MODEL,
            },
            "required": ["dataset"],
        },
    ),
    ToolSpec(
        "rank_series",
        "Ranking the series",
        "Best or worst forecast series of a dataset by holdout error.",
        {
            "type": "object",
            "properties": {
                "dataset": _DATASET,
                "which": {"type": "string", "enum": ["best", "worst"]},
                "n": {"type": "integer", "minimum": 1, "maximum": 20},
                "model": _MODEL,
            },
            "required": ["dataset"],
        },
    ),
    ToolSpec(
        "order_plan",
        "Planning orders",
        "Turn the forecast into a stocking decision: leftover stock needed for a target "
        "availability "
        "with the model's quantiles vs a classic forecast + safety buffer, the cost of lost sales "
        "vs leftovers, and the suggested order for the next period of one series. Shows a chart.",
        {
            "type": "object",
            "properties": {
                "dataset": _DATASET,
                "series": _SERIES,
                "scope": {
                    "type": "string",
                    "enum": ["all", "series"],
                    "description": "Score all series or just this one.",
                },
                "target_availability": {
                    "type": "number",
                    "minimum": 0.5,
                    "maximum": 0.995,
                    "description": "Fill rate, e.g. 0.95.",
                },
                "margin": {
                    "type": "number",
                    "description": "Margin lost per missed sale, share of value (default 0.4).",
                },
                "leftover_cost": {
                    "type": "number",
                    "description": "Cost of a leftover unit, share of value (default 0.15).",
                },
                "model": _MODEL,
            },
            "required": ["dataset"],
        },
    ),
    ToolSpec(
        "what_if",
        "Running the scenario",
        "Scenario on the future of one series by editing a covariate known in advance (e.g. Promo, "
        "Open for rossmann): mode set/shift/scale over forecast steps [start_step, end_step). "
        "Shows a chart.",
        {
            "type": "object",
            "properties": {
                "dataset": _DATASET,
                "series": _SERIES,
                "covariate": {"type": "string"},
                "mode": {"type": "string", "enum": ["set", "shift", "scale"]},
                "value": {"type": "number"},
                "start_step": {"type": "integer", "minimum": 0},
                "end_step": {"type": "integer", "minimum": 1},
                "horizon": _HORIZON,
                "model": _MODEL,
            },
            "required": ["dataset", "covariate", "value"],
        },
    ),
    ToolSpec(
        "detect_anomalies",
        "Scanning for anomalies",
        "Find unusual points in the recent past of one series (outside the model's 98% band).",
        {
            "type": "object",
            "properties": {
                "dataset": _DATASET,
                "series": _SERIES,
                "windows": {"type": "integer", "minimum": 1, "maximum": 100},
                "model": _MODEL,
            },
            "required": ["dataset"],
        },
    ),
]
LABELS = {spec.name: spec.label for spec in SPECS}


class Toolbox:
    """Runs a tool by name for one assistant, within its permissions."""

    def __init__(self, workbench, views: dict):
        self._workbench = workbench
        self._views = (
            views  # use cases by name: overview, ranking, planner, live, what_if, anomalies
        )
        self._tools: dict[str, Callable[[dict, ToolPermissions], ToolResult]] = {
            "list_datasets": self._list_datasets,
            "accuracy_summary": self._accuracy_summary,
            "forecast": self._forecast,
            "rank_series": self._rank_series,
            "order_plan": self._order_plan,
            "what_if": self._what_if,
            "detect_anomalies": self._anomalies,
        }

    @property
    def specs(self) -> list[ToolSpec]:
        return SPECS

    def call(self, name: str, arguments: dict, permissions: ToolPermissions) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"Unknown tool {name}. Available: {', '.join(self._tools)}")
        if not isinstance(arguments, dict):
            raise ToolError(f"The arguments for {name} must be a JSON object.")
        try:
            return tool(arguments, permissions)
        except (KeyError, TypeError, ValueError) as error:
            raise ToolError(f"{type(error).__name__}: {error}") from None

    # ------------------------------------------------------------------ helpers
    def _visible(self, permissions: ToolPermissions) -> list[Dataset]:
        return [ds for ds in self._workbench.catalog.list() if _allowed(ds, permissions)]

    def _dataset(self, name: str, permissions: ToolPermissions) -> Dataset:
        datasets = self._workbench.catalog.list()
        wanted = str(name).strip()
        found = next(
            (
                ds
                for ds in datasets
                if wanted in (ds.key, ds.name) or wanted.lower() == ds.name.lower()
            ),
            None,
        ) or next(
            (
                ds
                for ds in datasets
                if wanted.lower() in ds.name.lower() or wanted.lower() in ds.key
            ),
            None,
        )
        if found is None:
            keys = ", ".join(ds.key for ds in self._visible(permissions))
            raise ToolError(f"Unknown dataset '{name}'. Available: {keys}")
        if not _allowed(found, permissions):
            raise PolicyViolation(PRIVATE_REFUSAL.format(name=found.name))
        return found

    def _series(self, ds: Dataset, series) -> int:
        if series is None or series == "":
            return 0
        wanted = str(series).strip().lstrip("#")
        index = ds.series_index(wanted)
        if index is None:
            examples = ", ".join(ds.ids[:5])
            raise ToolError(
                f"Series '{series}' not found in {ds.key}. It has {ds.N} series with ids like "
                f"{examples}."
            )
        return index

    @staticmethod
    def _variant(model: str | None) -> str | None:
        if not model:
            return None
        repo = MODEL_SIZES.get(model)
        if repo is None:
            raise ToolError(f"Unknown model '{model}'. Use one of: {', '.join(MODEL_SIZES)}")
        return f"{repo}|cov|missing"

    def _scope(self, ds: Dataset, horizon=None):
        return self._workbench.scope(ds.key, horizon)

    # ------------------------------------------------------------------ tools
    def _list_datasets(self, _: dict, permissions: ToolPermissions) -> ToolResult:
        lines = []
        for ds in self._visible(permissions):
            meta = to_plain(dataset_meta(ds))
            covariates = ", ".join(c["name"] for c in meta["covariates"]) or "none"
            lines.append(
                f"- {meta['key']}: {meta['name']} | {meta['n']} series ({meta['id_label']} ids "
                "e.g. "
                f"{', '.join(meta['ids'][:3])}) | freq {meta['freq']}, {meta['start']} → "
                f"{meta['end']} | "
                f"unit {meta['unit']} | default horizon {meta['horizon']} | covariates: "
                f"{covariates}\n"
                f"  {meta['description']}"
            )
        hidden = len(self._workbench.catalog.list()) - len(lines)
        if hidden:
            lines.append(
                f"({hidden} private dataset(s) of the user are not shown to an external AI.)"
            )
        return ToolResult("\n".join(lines))

    def _accuracy_summary(self, args: dict, permissions: ToolPermissions) -> ToolResult:
        ds = self._dataset(args["dataset"], permissions)
        o = to_plain(self._views["overview"].execute(self._scope(ds)))
        primary = o["primary"]
        lines = [
            f"Dataset {o['meta']['name']}: holdout {o['holdout'][0]['start']} → "
            f"{o['holdout'][-1]['end']} "
            f"({o['windows']} window(s) × {o['H']} steps, {o['scored_points']:,} points scored, "
            "never seen "
            "by the model).",
            f"Primary metric: {primary}. Leaderboard (lower is better):",
        ]
        for r in o["leaderboard"][:8]:
            lines.append(
                f"- {r['name']} [{r['kind']}]: {primary} {r.get(primary)!s:.6} | WAPE "
                f"{pct(r.get('wape'))} | "
                f"MAPE {pct(r.get('mape'))} | bias {pct(r.get('bias'))} | 80% band coverage "
                f"{pct(r.get('coverage'))}"
            )
        if o.get("kpi"):
            k = o["kpi"]
            lines.append(
                f"Best model vs best classic method ({o['best_baseline']}): {pct(k.get('gain'))} "
                f"lower {primary}. "
                f"Compute time for the whole backtest on CPU: {num(k.get('secs_total'))} s."
            )
        if o.get("total_kpi") is not None:
            lines.append(
                f"Error on the sum of all series (bottom-up): MAPE {pct(o['total_kpi'], 2)}."
            )
        if o.get("best_series"):
            lines.append(
                "Easiest series: "
                + ", ".join(f"{x['id']} ({primary} {x['model']:.3f})" for x in o["best_series"][:3])
            )
            lines.append(
                "Hardest series: "
                + ", ".join(
                    f"{x['id']} ({primary} {x['model']:.3f})" for x in o["worst_series"][:3]
                )
            )
        top = o["leaderboard"][:8]
        chart = dict(
            kind="leaderboard",
            title=f"{o['meta']['name']} · {primary.upper()} on the holdout (lower is better)",
            data=dict(
                metric=primary,
                names=[r["name"] for r in top],
                values=[r.get(primary) for r in top],
                kinds=[r["kind"] for r in top],
            ),
        )
        return ToolResult("\n".join(lines), chart)

    def _forecast(self, args: dict, permissions: ToolPermissions) -> ToolResult:
        ds = self._dataset(args["dataset"], permissions)
        s = self._series(ds, args.get("series"))
        r = to_plain(
            self._views["live"].execute(
                self._scope(ds, args.get("horizon")),
                s,
                self._variant(args.get("model")),
                args.get("from_date"),
            )
        )
        f = r["forecast"]
        n = len(r["fdates"])
        total = sum(x for x in f["median"] if x is not None)
        lines = [
            f"{r['model']} forecast for {r['meta']['id_label']} {r['id']} of {r['meta']['name']} "
            f"from {r['origin']}, "
            f"{n} steps ({r['fdates'][0]} → {r['fdates'][-1]}), unit {r['meta']['unit']}, "
            "computed in "
            f"{num(r['seconds'], 2)} s on CPU.",
            f"Sum of the median over the horizon: {num(total)}; P10–P90 = 80% band.",
            "step | date | median | P10 | P90",
        ]
        for i in range(0, n, max(1, n // 14)):
            lines.append(
                f"{i} | {r['fdates'][i]} | {num(f['median'][i])} | {num(f['lo'][i])} | "
                f"{num(f['hi'][i])}"
            )
        m = r.get("metrics") or {}
        if m:
            lines.append(
                f"The real values are known for this period: MAPE {pct(m.get('mape'))}, WAPE "
                f"{pct(m.get('wape'))}, "
                f"bias {pct(m.get('bias'))}, coverage of the 80% band {pct(m.get('coverage'), 0)}."
            )
        else:
            lines.append("This is a true forecast of the future: reality is not known yet.")
        title = (
            f"{r['meta']['id_label']} {r['id']} · {r['meta']['name']} · forecast from {r['origin']}"
        )
        return ToolResult("\n".join(lines), dict(kind="forecast", title=title, data=r))

    def _rank_series(self, args: dict, permissions: ToolPermissions) -> ToolResult:
        ds = self._dataset(args["dataset"], permissions)
        ranked = to_plain(
            self._views["ranking"].execute(self._scope(ds), self._variant(args.get("model")))
        )
        ranked = [x for x in ranked if x["err"] is not None]
        n = max(1, min(int(args.get("n") or 5), 20))
        which = args.get("which", "worst")
        ranked.sort(key=lambda x: x["err"], reverse=which == "worst")
        primary = ds.primary
        shown = pct if primary in ("mape", "wape", "smape", "rmspe") else (lambda v: f"{v:.3f}")
        meaning = {
            "mape": "MAPE = average % error per point",
            "wape": "WAPE = total error / total volume",
            "mase": "MASE = error relative to the seasonal-naive rule, below 1 is better",
        }.get(primary, primary.upper())
        lines = [
            f"{which.capitalize()} {n} series by holdout error ({len(ranked)} series scored; "
            f"metric {meaning}; lower is better):"
        ]
        lines += [f"- {x['id']}: {shown(x['err'])}" for x in ranked[:n]]
        return ToolResult("\n".join(lines))

    def _order_plan(self, args: dict, permissions: ToolPermissions) -> ToolResult:
        ds = self._dataset(args["dataset"], permissions)
        s = self._series(ds, args.get("series"))
        request = PlanRequest(
            s,
            args.get("scope", "all"),
            float(args.get("margin", 0.4)),
            float(args.get("leftover_cost", 0.15)),
            float(args.get("target_availability", 0.95)),
        )
        r = to_plain(
            self._views["planner"].execute(
                self._scope(ds), self._variant(args.get("model")), request
            )
        )
        same, cost = r["same"], r["cost"]
        where = "all series" if r["scope"] == "all" else "series " + r["id"]
        lines = [
            f"Order planner on {r['meta']['name']} ({where}), holdout {r['windows'][0]['start']} → "
            f"{r['windows'][-1]['end']}, {r['points']:,} {r['period']}s scored. Assumptions: lost "
            "margin "
            f"{pct(r['margin'], 0)} of value per missed sale, leftover cost "
            f"{pct(r['holding'], 0)} of value.",
            f"At {pct(same['target'], 0)} availability (fill rate): the model needs leftover "
            "stock = "
            f"{pct(same.get('timestral'))} of demand (order ≈ "
            f"P{round((same.get('timestral_level') or 0) * 100)}), "
            f"the classic rule '{r['baseline']}' + buffer needs {pct(same.get('baseline'))} "
            "(buffer "
            f"×{num(same.get('baseline_buffer'), 2)}). Safety stock saving: "
            f"{pct(same.get('saving'))}.",
            f"Cost view (critical ratio {pct(cost['ratio'], 0)} → order "
            f"P{round(cost['level'] * 100)}):",
        ]
        for t in r["table"]:
            lines.append(
                f"- {t['name']}: fill {pct(t['fill'])}, leftover {pct(t['leftover_pct'])} of "
                f"demand, cost {num(t['cost'])}"
            )
        lines.append(
            "Saving vs the classic rule with its best buffer (chosen in hindsight, so favourable "
            "to it): "
            f"{num(cost['saving'])} ({pct(cost.get('saving_pct'))}) in {r['meta']['unit']} over "
            "the holdout; "
            f"≈ ×{num(cost['per_year'], 1)} for a year (rough extrapolation)."
        )
        plan = r["plan"]
        lines.append(
            f"Next {len(plan['future_dates'])} {r['period']}s for series {plan['id']}: expected "
            f"{num(plan['total_median'])}, suggested order {num(plan['total_order'])} "
            f"(P{round(cost['level'] * 100)} per {r['period']})."
        )
        return ToolResult(
            "\n".join(lines),
            dict(kind="planner", title=f"Order planner · {r['meta']['name']}", data=r),
        )

    def _what_if(self, args: dict, permissions: ToolPermissions) -> ToolResult:
        ds = self._dataset(args["dataset"], permissions)
        s = self._series(ds, args.get("series"))
        edit = Edit(
            args["covariate"],
            args.get("mode", "set"),
            float(args["value"]),
            int(args.get("start_step", 0)),
            args.get("end_step"),
        )
        request = WhatIfRequest(s, self._variant(args.get("model")), [edit])
        r = to_plain(self._views["what_if"].execute(self._scope(ds, args.get("horizon")), request))
        totals = r["totals"]
        names = [c["name"] for c in r["covariates"]]
        end = edit.end if edit.end is not None else "end"
        text = (
            f"What-if on {r['meta']['id_label']} {r['id']} of {r['meta']['name']} "
            f"({r['future_dates'][0]} → "
            f"{r['future_dates'][-1]}): {edit.name} {edit.mode} {edit.value:g} on steps "
            f"{edit.start}–{end}.\n"
            f"Total median: base {num(totals['base'])} → scenario {num(totals['scenario'])} "
            f"({pct(totals.get('pct'))}). "
            f"Known covariates available: {', '.join(names)}. Note: this is how the model reacts, "
            "not a measured "
            "causal effect."
        )
        title = (
            f"What-if · {r['meta']['id_label']} {r['id']} · {edit.name} {edit.mode} {edit.value:g}"
        )
        return ToolResult(text, dict(kind="whatif", title=title, data=r))

    def _anomalies(self, args: dict, permissions: ToolPermissions) -> ToolResult:
        ds = self._dataset(args["dataset"], permissions)
        s = self._series(ds, args.get("series"))
        r = to_plain(
            self._views["anomalies"].execute(
                self._scope(ds),
                s,
                self._variant(args.get("model")),
                None,
                int(args.get("windows", 20)),
                0.98,
            )
        )
        top = r["anomalies"][:8]
        lines = [
            f"Anomaly scan of {r['meta']['id_label']} {r['id']} ({r['windows']} windows × "
            f"{r['step']} steps, "
            f"98% band): {len(r['anomalies'])} points outside the band = {pct(r['rate'])} "
            f"(≈{pct(r['expected_rate'], 0)} expected by chance)."
        ]
        lines += [
            f"- {x['date']}: actual {num(x['actual'])}, expected {num(x['expected'])} (band "
            f"{num(x['lo'])}–"
            f"{num(x['hi'])}), {x['direction']}"
            for x in top
        ]
        return ToolResult("\n".join(lines))


def _allowed(ds: Dataset, permissions: ToolPermissions) -> bool:
    return not (ds.is_private and permissions.external and not permissions.private_data_allowed)


def pct(value, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def num(value, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:,.{digits}f}"
