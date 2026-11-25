# SPDX-License-Identifier: Apache-2.0
"""Fixtures for the golden tests: a running app on copied fixtures and snapshot comparison.

Snapshots live in tests/golden/snapshots. To approve a new behaviour on purpose, rerun with
JFB_UPDATE_GOLDEN=1 and review the diff of the JSON files before committing it.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

SNAPSHOTS = Path(__file__).parent / "snapshots"
DEFAULT_VARIANT = "mistralai/Timestral-28M|cov|missing"
SYNTHETIC_KEY = "synthetic"


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
    weekly = np.array([0.8, 1.0, 1.0, 1.1, 1.2, 1.5, 0.6])[dates.dayofweek]
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


# ----------------------------------------------------------------------------- snapshots
@pytest.fixture
def golden():
    """Compare a JSON-like value with its approved snapshot (floats with a relative tolerance)."""

    def check(name: str, value, rel: float = 1e-6, abs_tol: float = 1e-9, ignore=()) -> None:
        actual = _without_keys(json.loads(json.dumps(value)), set(ignore))
        path = SNAPSHOTS / f"{name}.json"
        if os.environ.get("JFB_UPDATE_GOLDEN") == "1":
            text = json.dumps(actual, indent=1, ensure_ascii=False) + "\n"
            path.write_text(text, encoding="utf-8")
            return
        assert path.exists(), f"no snapshot {path.name}: run once with JFB_UPDATE_GOLDEN=1"
        expected = json.loads(path.read_text(encoding="utf-8"))
        _assert_same(expected, actual, rel, abs_tol, where=name)

    return check


def _without_keys(value, ignore: set):
    if isinstance(value, dict):
        return {k: _without_keys(v, ignore) for k, v in value.items() if k not in ignore}
    if isinstance(value, list):
        return [_without_keys(v, ignore) for v in value]
    return value


def _assert_same(expected, actual, rel: float, abs_tol: float, where: str) -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{where}: expected an object"
        assert list(expected) == list(actual), f"{where}: keys differ"
        for key in expected:
            _assert_same(expected[key], actual[key], rel, abs_tol, f"{where}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{where}: expected a list"
        assert len(expected) == len(actual), f"{where}: length {len(actual)} != {len(expected)}"
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            _assert_same(e, a, rel, abs_tol, f"{where}[{i}]")
    elif isinstance(expected, float) and isinstance(actual, (int, float)):
        assert math.isclose(expected, actual, rel_tol=rel, abs_tol=abs_tol), (
            f"{where}: {actual} != {expected}"
        )
    else:
        assert expected == actual, f"{where}: {actual!r} != {expected!r}"
