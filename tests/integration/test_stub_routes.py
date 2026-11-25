# SPDX-License-Identifier: Apache-2.0
"""Every on-demand forecast route answers with the stub model: no weights, no network."""

from __future__ import annotations

import numpy as np
import pytest

from j_forecast_board import engine, settings
from j_forecast_board.stub_model import StubForecaster


@pytest.fixture
def stub_model(monkeypatch, scratch_home):
    stub = settings.Settings(home=scratch_home, model="stub")
    monkeypatch.setattr(settings, "current", lambda: stub)
    monkeypatch.setattr(engine, "_models", {})
    monkeypatch.setattr(engine, "Q_LEVELS", list(engine.Q_LEVELS))
    return stub


def test_the_engine_hands_out_the_stub(stub_model):
    assert isinstance(engine.get_model("mistralai/Timestral-28M"), StubForecaster)
    assert engine.model_cached("mistralai/Timestral-209M")


ROUTES = [
    ("api/live", {"dataset": "passengers"}),
    ("api/live", {"dataset": "bike", "origin": "2012-06-30"}),
    ("api/replay", {"dataset": "bike", "frames": 4}),
    ("api/split", {"dataset": "passengers"}),
    ("api/whatif", {"dataset": "bike", "edits": [{"name": "Holiday", "mode": "set", "value": 1}]}),
    ("api/anomalies", {"dataset": "passengers", "windows": 4}),
    ("api/live", {"dataset": "synthetic", "series": 2}),
]


@pytest.mark.parametrize(("path", "body"), ROUTES, ids=[f"{p}-{b['dataset']}" for p, b in ROUTES])
def test_on_demand_route_answers_with_the_stub(client, stub_model, path, body):
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    numbers = [v for v in _floats(response.json()) if v is not None]
    assert numbers and np.isfinite(numbers).all()


def test_live_forecast_of_the_stub_repeats_the_last_cycle(client, stub_model):
    body = client.post("api/live", json={"dataset": "passengers"}).json()
    last_year = body["y"][-12:]
    assert body["forecast"]["median"] == pytest.approx(last_year, rel=1e-4)


def _floats(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _floats(item)
    elif isinstance(value, list):
        for item in value:
            yield from _floats(item)
    elif isinstance(value, float):
        yield value
