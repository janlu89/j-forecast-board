# SPDX-License-Identifier: Apache-2.0
"""Test session setup: every test runs against a scratch runtime folder, never the real one.

The environment is prepared at import time, before any test module imports the app, because the
legacy modules read JFB_HOME and the credentials file when they are imported.
"""

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
def client(credentials):
    """The current app with only the two fixture datasets plus a synthetic three-series panel."""
    from j_forecast_board import data, evaluate, server

    data.LOADERS = [data.load_passengers, data.load_bike]  # no download of the other datasets
    with TestClient(server.app) as test_client:
        test_client.auth = credentials
        assert not evaluate.JOBS, "a fixture result is missing: the app queued a model run"
        _register_synthetic_panel(data, evaluate)
        yield test_client


def _register_synthetic_panel(data, evaluate) -> None:
    """Three daily series with a weekly cycle and a cached fake result, to cover the panel views."""
    ds = synthetic_dataset(data)
    data.DATASETS[ds.key] = ds
    evaluate.MEMO[(ds.key, ds.horizon, ds.context, DEFAULT_VARIANT)] = fake_result(ds, evaluate)


def synthetic_dataset(data):
    length, horizon, season = 210, 14, 7
    dates = pd.date_range("2024-01-01", periods=length, freq="D")
    steps = np.arange(length)
    weekly = np.array([0.8, 1.0, 1.0, 1.1, 1.2, 1.5, 0.6])[dates.day_of_week]
    level = np.array([100.0, 140.0, 60.0])[:, None]
    trend = np.array([0.2, 0.4, -0.05])[:, None] * steps[None, :]
    wiggle = np.array([3.0, 5.0, 8.0])[:, None] * np.sin(steps / 5.0)[None, :]
    values = (level + trend) * weekly[None, :] + wiggle
    values[1, 50:53] = np.nan
    return data.Dataset(
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


def fake_result(ds, evaluate) -> dict:
    """Deterministic quantiles shaped like a real backtest: last cycle repeated, fixed spread."""
    from j_forecast_board import engine

    levels = np.asarray(engine.Q_LEVELS)
    cuts = evaluate.windows(ds, ds.horizon)

    def quantiles(history: np.ndarray) -> np.ndarray:
        last_cycle = history[-ds.season :]
        last_cycle = np.where(np.isfinite(last_cycle), last_cycle, np.nanmean(history))
        median = np.resize(last_cycle, ds.horizon)
        spread = 0.15 * np.abs(median)
        return (median[:, None] + spread[:, None] * (levels[None, :] - 0.5) * 2).astype(np.float32)

    total = evaluate.total_series(ds)
    meta = dict(
        variant=DEFAULT_VARIANT,
        H=ds.horizon,
        L=ds.context,
        N=ds.N,
        created="2026-01-01 00:00",
        total_v=evaluate.TOTAL_V,
    )
    return dict(
        bt=np.stack([np.stack([quantiles(ds.Y[s, :c]) for c in cuts]) for s in range(ds.N)]),
        fut=np.stack([quantiles(ds.Y[s]) for s in range(ds.N)]),
        cuts=np.array(cuts),
        secs=np.array(1.5),
        secs_total=np.array(2.0),
        total_bt=np.stack([quantiles(total[:c]) for c in cuts]),
        total_fut=quantiles(total),
        meta=meta,
    )


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(SCRATCH_HOME, ignore_errors=True)
