# SPDX-License-Identifier: Apache-2.0
"""Validation and storage of the chat agent settings."""

from __future__ import annotations

import json
import secrets

import pytest

from j_forecast_board import agents


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "agents_config.json"
    monkeypatch.setattr(agents, "CONFIG", path)
    return path


def test_defaults_when_nothing_is_saved():
    listing = agents.listing()
    assert listing["active"] == "claude"
    assert [a["id"] for a in listing["agents"]] == ["claude", "openai", "local", "custom"]


def test_base_url_must_be_http_or_https():
    assert agents._check_url(" http://127.0.0.1:8090/v1/ ") == "http://127.0.0.1:8090/v1"
    for bad in ["", "ftp://host/v1", "127.0.0.1:8090", "http://"]:
        with pytest.raises(ValueError, match="Base URL"):
            agents._check_url(bad)


def test_claude_model_must_be_a_known_alias():
    with pytest.raises(ValueError, match="Claude model"):
        agents.update("claude", {"model": "gpt-4"}, make_active=False)


def test_an_api_agent_needs_a_model_before_activation():
    with pytest.raises(ValueError, match="Choose a model first"):
        agents.update("custom", {"base_url": "https://api.example/v1"}, make_active=True)


def test_overlong_values_are_refused():
    with pytest.raises(ValueError, match="API key too long"):
        agents.update("custom", {"api_key": "k" * 401}, make_active=False)
    with pytest.raises(ValueError, match="model too long"):
        agents.update("custom", {"model": "m" * 121}, make_active=False)


def test_unknown_agent_is_refused():
    with pytest.raises(ValueError, match="Unknown agent"):
        agents.update("nobody", {}, make_active=False)


def test_api_key_is_stored_but_never_listed(settings_file):
    key = secrets.token_urlsafe(16)  # generated: no key-like literal in the repository
    fields = {"base_url": "https://api.example/v1", "model": "m1", "api_key": key}
    listing = agents.update("custom", fields, make_active=True)
    custom = next(a for a in listing["agents"] if a["id"] == "custom")
    assert listing["active"] == "custom"
    assert custom["has_key"] and custom["key_hint"] == f"…{key[-4:]}"
    assert "api_key" not in custom
    assert key not in json.dumps(listing)
    assert json.loads(settings_file.read_text())["agents"]["custom"]["api_key"] == key
    assert agents.get("custom")["api_key"] == key


def test_an_empty_key_field_keeps_the_saved_key():
    key = secrets.token_urlsafe(16)
    agents.update("custom", {"api_key": key}, make_active=False)
    agents.update("custom", {"api_key": None, "model": "m2"}, make_active=False)
    assert agents.get("custom")["api_key"] == key


def test_unreadable_settings_fall_back_to_defaults(settings_file):
    settings_file.write_text("{not json", encoding="utf-8")
    assert agents.listing()["active"] == "claude"
