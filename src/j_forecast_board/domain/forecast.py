# SPDX-License-Identifier: Apache-2.0
"""Forecast values: model variants, requests and quantile forecasts."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import InvalidRequest

MODEL_REPOS = {
    "mistralai/Timestral-5M": "Timestral-5M",
    "mistralai/Timestral-28M": "Timestral-28M",
    "mistralai/Timestral-123M": "Timestral-123M",
    "mistralai/Timestral-209M": "Timestral-209M",
}
DEFAULT_REPO = "mistralai/Timestral-28M"
QUANTILE_LEVELS: tuple[float, ...] = (
    0.01,
    0.05,
    0.1,
    0.15,
    0.2,
    0.25,
    0.3,
    0.35,
    0.4,
    0.45,
    0.5,
    0.55,
    0.6,
    0.65,
    0.7,
    0.75,
    0.8,
    0.85,
    0.9,
    0.95,
    0.99,
)


def quantile_index(level: float, levels: tuple[float, ...] = QUANTILE_LEVELS) -> int:
    """Position of the level nearest to `level`."""
    return min(range(len(levels)), key=lambda i: abs(levels[i] - level))


def short_model_name(repo: str) -> str:
    """ "mistralai/Timestral-28M" -> "Timestral-28M" (used in cache file names)."""
    return repo.split("/")[-1]


@dataclass(frozen=True)
class ModelVariant:
    """Which model, and how it sees the data: with or without covariates, closed days as 0 or
    missing."""

    repo: str
    use_covariates: bool = True
    closed_as_zero: bool = False

    @classmethod
    def parse(cls, key: str) -> ModelVariant:
        try:
            repo, covariates, closed = key.split("|")
        except ValueError:
            raise InvalidRequest(f"Unknown model variant '{key}'.") from None
        if repo not in MODEL_REPOS:
            raise InvalidRequest(f"Unknown model {repo}")
        return cls(repo, covariates == "cov", closed == "zero")

    @property
    def key(self) -> str:
        covariates = "cov" if self.use_covariates else "nocov"
        closed = "zero" if self.closed_as_zero else "missing"
        return f"{self.repo}|{covariates}|{closed}"

    @property
    def size(self) -> str:
        return short_model_name(self.repo)

    def fit_to(self, has_covariates: bool, has_closures: bool) -> ModelVariant:
        """The canonical form for a dataset, as all_variants lists it: without covariates the flag
        stays on (it changes nothing), without closures "closed as zero" is off."""
        use_covariates = self.use_covariates if has_covariates else True
        return ModelVariant(self.repo, use_covariates, self.closed_as_zero and has_closures)

    def label(self, model_name: str, has_covariates: bool, has_closures: bool) -> str:
        text = model_name
        if has_covariates and not self.use_covariates:
            text += " · no covariates"
        if has_closures:
            text += " · closed = 0" if self.closed_as_zero else " · closed = missing"
        return text


def all_variants(has_covariates: bool, has_closures: bool) -> list[ModelVariant]:
    """Every variant a dataset supports, model by model."""
    return [
        ModelVariant(repo, covariates, zero)
        for repo in MODEL_REPOS
        for covariates in ([True, False] if has_covariates else [True])
        for zero in ([False, True] if has_closures else [False])
    ]


@dataclass(frozen=True)
class QuantileForecast:
    """Quantiles of a batch of forecasts: values (batch, horizon, levels)."""

    values: np.ndarray
    levels: tuple[float, ...] = QUANTILE_LEVELS

    def at(self, level: float) -> np.ndarray:
        """(batch, horizon) values of the quantile nearest to `level`."""
        return self.values[..., quantile_index(level, self.levels)]

    @property
    def median(self) -> np.ndarray:
        return self.at(0.5)


@dataclass(frozen=True)
class SeriesForecastRequest:
    """Forecasts of one dataset: series s seen up to cut c, for each (s, c) item."""

    items: list[tuple[int, int]]
    horizon: int
    context: int  # 0 = all the history
    variant: ModelVariant
    overrides: dict[str, np.ndarray] | None = None  # scenario values of known covariates (N, T + H)
    chunk: int = 64

    def __post_init__(self):
        if self.horizon < 1:
            raise InvalidRequest("Horizon must be >= 1")
        if not self.items:
            raise InvalidRequest("Nothing to forecast.")
