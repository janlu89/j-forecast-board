# SPDX-License-Identifier: Apache-2.0
"""Test session setup: every test runs against a scratch runtime folder, never the real one."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "golden" / "fixtures"
DEFAULT_VARIANT = "mistralai/Timestral-28M|cov|missing"
SYNTHETIC_KEY = "synthetic"

SCRATCH_HOME = Path(tempfile.mkdtemp(prefix="jfb-test-"))
shutil.copytree(FIXTURES, SCRATCH_HOME, dirs_exist_ok=True)

TEST_USER = "tester"
TEST_PASSWORD = secrets.token_urlsafe(16)
(SCRATCH_HOME / "secrets").mkdir()
# The older plain-text format: the app hashes it on first use (covered by the tests).
(SCRATCH_HOME / "secrets" / "credentials.json").write_text(
    json.dumps({"utente": TEST_USER, "password": TEST_PASSWORD}), encoding="utf-8"
)

os.environ["JFB_HOME"] = str(SCRATCH_HOME)
os.environ["HF_HUB_OFFLINE"] = "1"  # tests never download weights


@pytest.fixture(scope="session")
def credentials() -> tuple[str, str]:
    """User name and password of the scratch install."""
    return TEST_USER, TEST_PASSWORD


@pytest.fixture(scope="session")
def scratch_home() -> Path:
    return SCRATCH_HOME


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------------------- app
@pytest.fixture(scope="session")
def container():
    """The real wiring, with only the two fixture datasets (no download of the others)."""
    from j_forecast_board.adapters.outbound.datasets.builtin import bike, passengers
    from j_forecast_board.bootstrap.container import build
    from j_forecast_board.bootstrap.settings import Settings

    settings = Settings(home=SCRATCH_HOME, offline=True)
    return build(settings, loaders={"passengers": passengers.load, "bike": bike.load})


@pytest.fixture(scope="session")
def client(container, credentials):
    """The app with the fixture datasets plus a synthetic three-series panel."""
    from j_forecast_board.bootstrap.app_factory import create_app

    with TestClient(create_app(container)) as test_client:
        test_client.auth = credentials
        assert not container.runner.all(), "a fixture result is missing: the app queued a model run"
        _register_synthetic_panel(container)
        yield test_client


def _register_synthetic_panel(container) -> None:
    """Three daily series with a weekly cycle and a cached fake result, to cover the panel views."""
    from j_forecast_board.domain.forecast import ModelVariant

    ds = synthetic_dataset()
    container.catalog.register(ds)
    evaluations = container.workbench.evaluations
    variant = ModelVariant.parse(DEFAULT_VARIANT)
    evaluations.remember(ds, ds.horizon, ds.context, variant, fake_result(ds))


def synthetic_dataset():
    from j_forecast_board.domain.series import Dataset

    length, horizon, season = 210, 14, 7
    dates = pd.date_range("2024-01-01", periods=length, freq="D")
    steps = np.arange(length)
    weekly = np.array([0.8, 1.0, 1.0, 1.1, 1.2, 1.5, 0.6])[dates.day_of_week]
    level = np.array([100.0, 140.0, 60.0])[:, None]
    trend = np.array([0.2, 0.4, -0.05])[:, None] * steps[None, :]
    wiggle = np.array([3.0, 5.0, 8.0])[:, None] * np.sin(steps / 5.0)[None, :]
    values = (level + trend) * weekly[None, :] + wiggle
    values[1, 50:53] = np.nan
    return Dataset(
        SYNTHETIC_KEY,
        "Synthetic stores",
        "Three made-up daily series for tests.",
        "units",
        "D",
        season,
        horizon,
        0,
        dates,
        values,
        ids=["A", "B", "C"],
        id_label="Store",
        attrs={"Region": ["north", "south", "north"]},
        persist=False,
        source="tests",
    )


def fake_result(ds):
    """Deterministic quantiles shaped like a real backtest: last cycle repeated, fixed spread."""
    from j_forecast_board.application.evaluations import TOTAL_VERSION
    from j_forecast_board.application.ports import BacktestResult
    from j_forecast_board.domain.evaluation import holdout_cuts
    from j_forecast_board.domain.forecast import QUANTILE_LEVELS

    levels = np.asarray(QUANTILE_LEVELS)
    cuts = holdout_cuts(ds, ds.horizon)

    def quantiles(history: np.ndarray) -> np.ndarray:
        last_cycle = history[-ds.season :]
        last_cycle = np.where(np.isfinite(last_cycle), last_cycle, np.nanmean(history))
        median = np.resize(last_cycle, ds.horizon)
        spread = 0.15 * np.abs(median)
        return (median[:, None] + spread[:, None] * (levels[None, :] - 0.5) * 2).astype(np.float32)

    total = ds.total()
    meta = dict(
        variant=DEFAULT_VARIANT,
        H=ds.horizon,
        L=ds.context,
        N=ds.N,
        created="2026-01-01 00:00",
        total_v=TOTAL_VERSION,
    )
    return BacktestResult(
        bt=np.stack([np.stack([quantiles(ds.Y[s, :c]) for c in cuts]) for s in range(ds.N)]),
        fut=np.stack([quantiles(ds.Y[s]) for s in range(ds.N)]),
        cuts=np.array(cuts),
        secs=1.5,
        secs_total=2.0,
        total_bt=np.stack([quantiles(total[:c]) for c in cuts]),
        total_fut=quantiles(total),
        meta=meta,
    )


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(SCRATCH_HOME, ignore_errors=True)
