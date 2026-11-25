# SPDX-License-Identifier: Apache-2.0
"""What every view needs: the dataset catalog, the evaluations and the model,
plus request checks."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import InvalidRequest, NotFound
from ..domain.evaluation import context_length
from ..domain.forecast import ModelVariant
from ..domain.series import Dataset
from .evaluations import Evaluations
from .ports import DatasetCatalog, ForecastModel


@dataclass(frozen=True)
class Scope:
    """A dataset with the horizon and context length a request asks for."""

    ds: Dataset
    horizon: int
    context: int


class Workbench:
    def __init__(
        self,
        catalog: DatasetCatalog,
        evaluations: Evaluations,
        model: ForecastModel,
        default_variant: ModelVariant,
    ):
        self.catalog = catalog
        self.evaluations = evaluations
        self.model = model
        self.default_variant = default_variant

    def scope(self, dataset: str, horizon: int | None = None, context: int | None = None) -> Scope:
        ds = self.catalog.get(dataset)
        steps = int(horizon or ds.horizon)
        if steps < 1:
            raise InvalidRequest("Horizon must be >= 1")
        return Scope(ds, steps, context_length(ds, context))

    def variant(self, ds: Dataset, key: str | None) -> ModelVariant:
        return self.evaluations.normalise(ds, key, self.default_variant)

    def default_variants(self, ds: Dataset) -> list[ModelVariant]:
        """Evaluated in the background at start: covariates on, then off, then closed days as 0."""
        repo = self.default_variant.repo
        out = [ModelVariant(repo, True, False)]
        if ds.covs:
            out.append(ModelVariant(repo, False, False))
        if ds.closed is not None:
            out.append(ModelVariant(repo, True, True))
        return out

    def series(self, ds: Dataset, index: int) -> int:
        if not 0 <= index < ds.N:
            raise NotFound(f"Series {index} does not exist in {ds.name} ({ds.N} series).")
        return index

    def label(self, ds: Dataset, variant: ModelVariant) -> str:
        return self.evaluations.label(ds, variant)
