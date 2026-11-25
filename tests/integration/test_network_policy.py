# SPDX-License-Identifier: Apache-2.0
"""With the network cut off except this PC, every route still works (stub model, offline mode).

The app may talk only to: Hugging Face for weights, the dataset hosts, and the AI service the user
configured. Offline and on the stub model it must need none of them.
"""

from __future__ import annotations

import shutil
import socket
import time

import pytest
from fastapi.testclient import TestClient

from j_forecast_board.adapters.outbound.datasets.builtin import bike, passengers
from j_forecast_board.bootstrap.app_factory import create_app
from j_forecast_board.bootstrap.container import build
from j_forecast_board.bootstrap.settings import Settings

LOOPBACK = ("127.0.0.1", "::1", "localhost")


@pytest.fixture
def no_internet(monkeypatch):
    attempts = []
    real_connect = socket.socket.connect

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOOPBACK:
            attempts.append(address)
            raise OSError(f"blocked by the test: {address}")
        return real_connect(self, address)

    def resolve(host, *args, **kwargs):
        if host not in LOOPBACK:
            attempts.append(host)
            raise socket.gaierror(f"blocked by the test: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    real_getaddrinfo = socket.getaddrinfo
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    return attempts


def test_every_route_works_without_internet(no_internet, tmp_path, repo_root, credentials):
    home = tmp_path / "home"
    shutil.copytree(repo_root / "tests" / "golden" / "fixtures" / "data", home / "data")
    settings = Settings(home=home, model="stub", offline=True)
    container = build(settings, loaders={"passengers": passengers.load, "bike": bike.load})
    with TestClient(create_app(container), raise_server_exceptions=True) as client:
        password = (home / "secrets" / "initial-password.txt").read_text().strip()
        client.auth = ("admin", password)
        evaluations = container.workbench.evaluations
        for _ in range(400):  # the stub evaluates the two datasets in the background
            if not evaluations.any_running():
                break
            time.sleep(0.05)
        series = {"dataset": "bike", "series": 0}
        for path in (
            "",
            "api/datasets",
            "api/models",
            "api/system",
            "api/assistant",
            "static/js/main.js",
        ):
            assert client.get(path).status_code == 200, path
        for path, body in [
            ("api/status", {"dataset": "bike"}), ("api/overview", {"dataset": "bike"}),
            ("api/series", series), ("api/ranking", series), ("api/planner", series),
            ("api/live", series), ("api/replay", {**series, "frames": 3}), ("api/split", series),
            ("api/whatif", series), ("api/anomalies", {**series, "windows": 3}),
        ]:  # fmt: skip
            response = client.post(path, json=body)
            assert response.status_code == 200, (path, response.text)
        with (repo_root / "examples" / "sample_store_sales.csv").open("rb") as handle:
            assert (
                client.post("api/upload", files={"file": ("s.csv", handle, "text/csv")}).status_code
                == 200
            )
    assert no_internet == [], f"the app tried to reach: {no_internet}"
