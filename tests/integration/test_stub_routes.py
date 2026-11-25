# SPDX-License-Identifier: Apache-2.0
"""Every on-demand forecast route answers with the stub model: no weights, no network."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from j_forecast_board.adapters.outbound.datasets.builtin import bike, passengers
from j_forecast_board.adapters.outbound.models.stub_model import StubModel
from j_forecast_board.bootstrap.app_factory import create_app
from j_forecast_board.bootstrap.container import build
from j_forecast_board.bootstrap.settings import Settings


@pytest.fixture(scope="module")
def stub_client(scratch_home, credentials):
    settings = Settings(home=scratch_home, model="stub", offline=True, background_eval=False)
    container = build(settings, loaders={"passengers": passengers.load, "bike": bike.load})
    with TestClient(create_app(container)) as client:
        client.auth = credentials
        yield client


def test_the_container_hands_out_the_stub(stub_client):
    container = stub_client.app.state.container
    assert isinstance(container.model, StubModel)
    assert container.model.is_available("mistralai/Timestral-209M")
    assert container.model.display_name("mistralai/Timestral-28M") == "Timestral-28M · stub"


ROUTES = [
    ("api/live", {"dataset": "passengers"}),
    ("api/live", {"dataset": "bike", "origin": "2012-06-30"}),
    ("api/replay", {"dataset": "bike", "frames": 4}),
    ("api/split", {"dataset": "passengers"}),
    ("api/whatif", {"dataset": "bike", "edits": [{"name": "Holiday", "mode": "set", "value": 1}]}),
    ("api/anomalies", {"dataset": "passengers", "windows": 4}),
]


@pytest.mark.parametrize(("path", "body"), ROUTES, ids=[f"{p}-{b['dataset']}" for p, b in ROUTES])
def test_on_demand_route_answers_with_the_stub(stub_client, path, body):
    response = stub_client.post(path, json=body)
    assert response.status_code == 200, response.text
    numbers = [v for v in _floats(response.json()) if v is not None]
    assert numbers and np.isfinite(numbers).all()


def test_live_forecast_of_the_stub_repeats_the_last_cycle(stub_client):
    body = stub_client.post("api/live", json={"dataset": "passengers"}).json()
    assert body["forecast"]["median"] == pytest.approx(body["y"][-12:], rel=1e-4)
    assert body["model"] == "Timestral-28M · stub"


def test_the_stub_evaluates_a_dataset_in_the_background(stub_client):
    import time

    run = stub_client.post(
        "api/run", json={"dataset": "passengers", "variant": "mistralai/Timestral-5M|cov|missing"}
    )
    assert run.status_code == 200
    for _ in range(200):
        status = stub_client.post("api/status", json={"dataset": "passengers"}).json()
        states = {v["key"]: v["state"] for v in status["variants"]}
        if states["mistralai/Timestral-5M|cov|missing"] == "done":
            break
        time.sleep(0.05)
    assert states["mistralai/Timestral-5M|cov|missing"] == "done"


def _floats(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _floats(item)
    elif isinstance(value, list):
        for item in value:
            yield from _floats(item)
    elif isinstance(value, float):
        yield value
