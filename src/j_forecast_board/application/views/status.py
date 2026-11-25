# SPDX-License-Identifier: Apache-2.0
"""Evaluation status of a dataset (which model variants are computed, running, queued) and starting
one."""

from __future__ import annotations

from ...domain.forecast import all_variants
from ..view_model import number
from ..workbench import Scope, Workbench


class EvaluationStatus:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(self, scope: Scope) -> dict:
        ds, horizon, context = scope.ds, scope.horizon, scope.context
        evaluations = self._workbench.evaluations
        done = {v.key for v in evaluations.available(ds, horizon, context)}
        variants = []
        for variant in all_variants(bool(ds.covs), ds.closed is not None):
            job = evaluations.job(ds, horizon, context, variant)
            is_done = variant.key in done
            variants.append(
                dict(
                    key=variant.key,
                    label=evaluations.label(ds, variant),
                    done=is_done,
                    model=self._workbench.model.display_name(variant.repo),
                    state="done" if is_done else (job.state if job else "idle"),
                    progress=number(job.done / max(1, job.total or 1)) if job else None,
                    eta=number(job.eta) if job else None,
                    error=job.error if job else None,
                )
            )
        return dict(
            H=horizon,
            L=context,
            variants=variants,
            jobs=evaluations.jobs_for(ds),
            any_running=evaluations.any_running(),
        )


class StartEvaluation:
    def __init__(self, workbench: Workbench):
        self._workbench = workbench

    def execute(self, scope: Scope, variant_key: str) -> dict:
        variant = self._workbench.variant(scope.ds, variant_key)
        state = self._workbench.evaluations.submit(scope.ds, scope.horizon, scope.context, variant)
        return dict(state=state)
