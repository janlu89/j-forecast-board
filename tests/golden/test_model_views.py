# SPDX-License-Identifier: Apache-2.0
"""Golden tests of the on-demand forecasts, with the real Timestral-28M on the CPU.

They need the weights in the local Hugging Face cache and never download them.
Run on a developer PC with `pytest -m model`; never on CI.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

MODEL = "mistralai/Timestral-28M"
REL = 1e-3  # CPU inference: allow tiny numeric drift between runs and machines
ABS = 1e-4

pytestmark = pytest.mark.model


@pytest.fixture(scope="module", autouse=True)
def weights_present(container):
    if not container.model.is_available(MODEL):
        pytest.skip(f"{MODEL} is not in the local Hugging Face cache")


def forecast(client, path: str, body: dict) -> dict:
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    return response.json()


CASES = [
    ("live_passengers", "api/live", {"dataset": "passengers"}),
    ("live_bike_origin", "api/live", {"dataset": "bike", "origin": "2012-06-30"}),
    ("replay_passengers", "api/replay", {"dataset": "passengers", "frames": 6}),
    ("replay_bike", "api/replay", {"dataset": "bike", "frames": 4}),
    ("split_passengers", "api/split", {"dataset": "passengers"}),
    ("split_bike", "api/split", {"dataset": "bike", "split": "2012-06-30"}),
    (
        "whatif_bike",
        "api/whatif",
        {
            "dataset": "bike",
            "edits": [{"name": "Temperature °C", "mode": "shift", "value": 5, "end": 14}],
        },
    ),
    ("anomalies_passengers", "api/anomalies", {"dataset": "passengers", "windows": 6}),
    ("anomalies_bike", "api/anomalies", {"dataset": "bike", "windows": 6}),
]


@pytest.mark.parametrize(("name", "path", "body"), CASES, ids=[c[0] for c in CASES])
def test_on_demand_forecast_matches_snapshot(client, golden, name, path, body):
    golden(name, forecast(client, path, body), rel=REL, abs_tol=ABS, ignore={"seconds"})


def test_what_if_needs_covariates_known_in_advance(client):
    browser = TestClient(client.app, raise_server_exceptions=False)
    browser.auth = client.auth
    response = browser.post("api/whatif", json={"dataset": "passengers"})
    assert response.status_code == 400
    assert "no covariates known in advance" in response.json()["error"]
