# SPDX-License-Identifier: Apache-2.0
"""Golden tests of the views computed from cached backtests (no model needed)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

FIXTURE_DATASETS = ["passengers", "bike"]
ALL_DATASETS = [*FIXTURE_DATASETS, "synthetic"]


def as_browser(client) -> TestClient:
    """A client that receives error responses as the browser does, instead of the exception."""
    browser = TestClient(client.app, raise_server_exceptions=False)
    browser.auth = client.auth
    return browser


def post(client, path: str, body: dict) -> dict:
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_dataset_catalog_lists_fixture_and_synthetic_datasets(client, golden):
    response = client.get("api/datasets")
    assert response.status_code == 200
    golden("datasets", response.json())


@pytest.mark.parametrize("key", ALL_DATASETS)
def test_status_reports_cached_variants(client, golden, key):
    golden(f"status_{key}", post(client, "api/status", {"dataset": key}))


@pytest.mark.parametrize("key", ALL_DATASETS)
def test_overview_matches_snapshot(client, golden, key):
    golden(f"overview_{key}", post(client, "api/overview", {"dataset": key}))


@pytest.mark.parametrize("key", ALL_DATASETS)
def test_series_view_matches_snapshot(client, golden, key):
    golden(f"series_{key}", post(client, "api/series", {"dataset": key, "series": 0}))


def test_series_view_of_a_later_series_in_a_panel(client, golden):
    body = {"dataset": "synthetic", "series": 1}
    golden("series_synthetic_1", post(client, "api/series", body))


@pytest.mark.parametrize("key", ALL_DATASETS)
def test_ranking_matches_snapshot(client, golden, key):
    golden(f"ranking_{key}", post(client, "api/ranking", {"dataset": key}))


@pytest.mark.parametrize("key", ALL_DATASETS)
def test_planner_all_series_matches_snapshot(client, golden, key):
    golden(f"planner_{key}", post(client, "api/planner", {"dataset": key}))


@pytest.mark.parametrize("key", ALL_DATASETS)
def test_planner_single_series_matches_snapshot(client, golden, key):
    body = {"dataset": key, "scope": "series", "series": 0, "margin": 0.5, "holding": 0.2}
    golden(f"planner_series_{key}", post(client, "api/planner", body))


def test_total_view_of_a_panel_matches_snapshot(client, golden):
    golden("total_synthetic", post(client, "api/total", {"dataset": "synthetic"}))


def test_total_view_refuses_a_single_series(client):
    response = as_browser(client).post("api/total", json={"dataset": "passengers"})
    assert response.status_code == 400
    assert "single series" in response.json()["error"]


def test_unknown_dataset_is_an_error(client):
    response = as_browser(client).post("api/overview", json={"dataset": "nope"})
    assert response.status_code == 400
    assert response.json() == {"error": "ValueError: Unknown dataset nope"}


def test_upload_preview_of_the_sample_file(client, golden, repo_root):
    sample = repo_root / "esempio_vendite_negozi.csv"
    with sample.open("rb") as handle:
        response = client.post("api/upload", files={"file": (sample.name, handle, "text/csv")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["uid"]) == 8
    golden("upload_sample", body, ignore={"uid"})
