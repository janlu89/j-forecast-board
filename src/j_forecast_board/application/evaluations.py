# SPDX-License-Identifier: Apache-2.0
"""Backtest evaluations: compute them in the background, cache them, and score them."""

from __future__ import annotations

import time

import numpy as np

from ..domain.baselines import baseline, baseline_names
from ..domain.calendar import aggregated_known
from ..domain.evaluation import holdout_cuts
from ..domain.forecast import ModelVariant, SeriesForecastRequest, all_variants, quantile_index
from ..domain.metrics import actuals, eval_mask, mase_scale, metrics
from ..domain.series import Dataset
from .ports import BacktestResult, ForecastModel, JobRunner, JobState, ResultStore

TOTAL_VERSION = 2  # version of the direct-total forecast (2 = with aggregated known covariates)
USER_PRIORITY = 0  # a request from the user overtakes the background evaluation (1, 2)


class Evaluations:
    """Which backtests exist, which are running, and the scoring panel built from them."""

    def __init__(self, model: ForecastModel, store: ResultStore, runner: JobRunner):
        self.model = model
        self._store = store
        self._runner = runner
        self._memo: dict[tuple, BacktestResult] = {}
        self._panel: tuple | None = None  # (key, dataset, Panel)

    # ------------------------------------------------------------------ labels
    def label(self, ds: Dataset, variant: ModelVariant) -> str:
        return variant.label(
            self.model.display_name(variant.repo), bool(ds.covs), ds.closed is not None
        )

    def normalise(self, ds: Dataset, key: str | None, default: ModelVariant) -> ModelVariant:
        variant = ModelVariant.parse(key) if key else default
        return variant.fit_to(bool(ds.covs), ds.closed is not None)

    # ------------------------------------------------------------------ results
    def result(
        self, ds: Dataset, horizon: int, context: int, variant: ModelVariant
    ) -> BacktestResult | None:
        key = (ds.key, horizon, context, variant.key)
        if key in self._memo:
            return self._memo[key]
        if not ds.persist:
            return None
        stored = self._store.find(ds, horizon, context, variant.key)
        if stored is None:
            return None
        if (
            ds.N > 1 and stored.meta.get("total_v") != TOTAL_VERSION
        ):  # older file: refresh the total
            self._forecast_total(ds, horizon, context, variant, stored)
            stored.meta["total_v"] = TOTAL_VERSION
            self._store.save(ds, horizon, context, variant.key, stored)
        self._memo[key] = stored
        return stored

    def remember(
        self, ds: Dataset, horizon: int, context: int, variant: ModelVariant, result: BacktestResult
    ):
        """Keep a result in memory (used for uploads and tests)."""
        self._memo[(ds.key, horizon, context, variant.key)] = result

    def available(self, ds: Dataset, horizon: int, context: int) -> list[ModelVariant]:
        return [
            v
            for v in all_variants(bool(ds.covs), ds.closed is not None)
            if self.result(ds, horizon, context, v) is not None
        ]

    def forget(self, ds: Dataset) -> None:
        for key in [k for k in self._memo if k[0] == ds.key]:
            del self._memo[key]
        self._store.delete_for(ds)
        self._panel = None

    # ------------------------------------------------------------------ jobs
    def submit(
        self,
        ds: Dataset,
        horizon: int,
        context: int,
        variant: ModelVariant,
        priority: int = USER_PRIORITY,
    ) -> str:
        """Queue an evaluation unless it is done; returns its state."""
        if self.result(ds, horizon, context, variant) is not None:
            return "done"
        info = dict(
            dataset=ds.key,
            H=horizon,
            L=context,
            variant=variant.key,
            label=self.label(ds, variant),
            series=ds.N,
        )
        job = self._runner.submit(
            self._job_key(ds, horizon, context, variant),
            lambda state: self._evaluate(ds, horizon, context, variant, state),
            priority,
            info,
        )
        return job.state

    def job(
        self, ds: Dataset, horizon: int, context: int, variant: ModelVariant
    ) -> JobState | None:
        return self._runner.get(self._job_key(ds, horizon, context, variant))

    def jobs_for(self, ds: Dataset) -> list[dict]:
        return [
            j.as_dict()
            for j in self._runner.all()
            if j.key[0] == ds.key and j.state in ("queued", "running", "error")
        ]

    def any_running(self) -> bool:
        return any(j.active for j in self._runner.all())

    @staticmethod
    def _job_key(ds: Dataset, horizon: int, context: int, variant: ModelVariant) -> tuple:
        return (ds.key, horizon, context, variant.key)

    def _evaluate(
        self, ds: Dataset, horizon: int, context: int, variant: ModelVariant, job: JobState
    ):
        cuts = holdout_cuts(ds, horizon)
        items = [(s, c) for s in range(ds.N) for c in cuts] + [(s, ds.T) for s in range(ds.N)]
        job.total = len(items)

        def progress(done: int, total: int) -> None:
            job.done = done
            elapsed = time.time() - job.started
            job.eta = elapsed / max(done, 1) * (total - done)

        request = SeriesForecastRequest(items, horizon, context, variant, chunk=32)
        forecast, seconds = self.model.forecast(ds, request, progress)
        holdout_items = ds.N * len(cuts)
        q = forecast.values
        result = BacktestResult(
            bt=q[:holdout_items].reshape(ds.N, len(cuts), horizon, -1),
            fut=q[holdout_items:],
            cuts=np.array(cuts),
            secs=seconds * holdout_items / len(items),
            secs_total=seconds,
            meta=dict(
                variant=variant.key,
                H=horizon,
                L=context,
                N=ds.N,
                created=time.strftime("%Y-%m-%d %H:%M"),
                total_v=TOTAL_VERSION,
            ),
            levels=forecast.levels,
        )
        if ds.N > 1:  # direct forecast of the aggregated total, for comparison with bottom-up
            self._forecast_total(ds, horizon, context, variant, result)
        if ds.persist:
            self._store.save(ds, horizon, context, variant.key, result)
        self.remember(ds, horizon, context, variant, result)

    def _forecast_total(self, ds, horizon, context, variant: ModelVariant, result: BacktestResult):
        total = ds.total()
        known = aggregated_known(ds, horizon) if variant.use_covariates else None
        forecasts = [
            self.model.forecast_one(total[:cut], horizon, context, variant.repo, known).values
            for cut in [*holdout_cuts(ds, horizon), ds.T]
        ]
        result.total_bt, result.total_fut = np.stack(forecasts[:-1]), forecasts[-1]

    # ------------------------------------------------------------------ scoring
    def panel(self, ds: Dataset, horizon: int, context: int) -> Panel:
        variants = tuple(v.key for v in self.available(ds, horizon, context))
        key = (ds.key, horizon, context, variants)
        if self._panel is None or self._panel[0] != key or self._panel[1] is not ds:
            self._panel = (key, ds, Panel(ds, horizon, context, self))
        return self._panel[2]


class Panel:
    """Everything needed to score all models on one dataset, horizon and context."""

    def __init__(self, ds: Dataset, horizon: int, context: int, evaluations: Evaluations):
        self.ds, self.H, self.L = ds, horizon, context
        self.cuts = holdout_cuts(ds, horizon)
        self.items = [(s, c) for s in range(ds.N) for c in self.cuts]
        windows = len(self.cuts)
        shape = (ds.N, windows, horizon)
        self.A = actuals(ds, self.items, horizon).reshape(shape)
        self.M = eval_mask(ds, self.A.reshape(-1, horizon), self.items, horizon).reshape(shape)
        scales = np.array([mase_scale(ds, s, self.cuts[0]) for s in range(ds.N)])
        self.scale = np.broadcast_to(scales[:, None, None], shape)
        self.rows: list[dict] = []  # name, kind, key, P (N, W, H), Q or None, secs, res
        for variant in evaluations.available(ds, horizon, context):
            result = evaluations.result(ds, horizon, context, variant)
            if result.bt.shape[:3] != shape:
                continue
            self.rows.append(
                dict(
                    name=evaluations.label(ds, variant),
                    kind="timestral",
                    key=variant.key,
                    P=result.bt[..., quantile_index(0.5, result.levels)],
                    Q=result.bt,
                    secs=float(result.secs),
                    res=result,
                    levels=result.levels,
                )
            )
        for key, label in baseline_names(ds).items():
            forecasts = np.stack(
                [
                    np.stack([baseline(ds, key, s, c, horizon) for c in self.cuts])
                    for s in range(ds.N)
                ]
            )
            self.rows.append(
                dict(name=label, kind="baseline", key=key, P=forecasts, Q=None, secs=None)
            )

    @property
    def model_rows(self) -> list[dict]:
        return [r for r in self.rows if r["kind"] == "timestral"]

    @property
    def baseline_rows(self) -> list[dict]:
        return [r for r in self.rows if r["kind"] == "baseline"]

    def row_for(self, variant_key: str | None) -> dict | None:
        """The model row of a variant, else the first model row."""
        rows = self.model_rows
        return next((r for r in rows if r["key"] == variant_key), None) or (
            rows[0] if rows else None
        )

    def score(self, row: dict, selection=None) -> dict:
        actual, predicted, mask, scale, quantiles = self.A, row["P"], self.M, self.scale, row["Q"]
        if selection is not None:
            actual, predicted, mask, scale = (
                actual[selection],
                predicted[selection],
                mask[selection],
                scale[selection],
            )
            quantiles = quantiles[selection] if quantiles is not None else None
        return metrics(actual, predicted, mask, scale, quantiles, row.get("levels") or ())

    def per_series(self, row: dict, metric: str) -> np.ndarray:
        out = np.full(self.ds.N, np.nan)
        for s in range(self.ds.N):
            scores = metrics(self.A[s], row["P"][s], self.M[s], self.scale[s])
            if scores and scores.get(metric) is not None:
                out[s] = scores[metric]
        return out

    def best_baseline(self) -> dict:
        primary = self.ds.primary

        def error(row):
            value = self.score(row).get(primary)
            return value if value is not None else 1e9

        return min(self.baseline_rows, key=error)
