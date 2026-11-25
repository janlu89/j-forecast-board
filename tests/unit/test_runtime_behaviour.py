# SPDX-License-Identifier: Apache-2.0
"""Behaviour driven by the settings: offline mode, first-start credentials, login switch."""

from __future__ import annotations

import json
import os
import stat

import pytest

from j_forecast_board import auth, data, settings


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "current", lambda: settings.Settings(home=tmp_path, offline=True))


def test_offline_mode_refuses_to_download_a_dataset(offline, monkeypatch, tmp_path):
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="JFB_OFFLINE=1"):
        data.download("https://example.invalid/data.csv", "data.csv")


def test_offline_mode_still_reads_a_downloaded_dataset(offline, monkeypatch, tmp_path):
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    (tmp_path / "data.csv").write_bytes(b"a,b\n1,2\n")
    assert data.download("https://example.invalid/data.csv", "data.csv") == b"a,b\n1,2\n"


def test_first_start_creates_private_credentials_and_prints_them_once(
    monkeypatch, tmp_path, capsys
):
    path = tmp_path / "credentials.json"
    monkeypatch.setattr(auth, "CREDENTIALS", path)
    user, password = auth._load_credentials()
    printed = capsys.readouterr().out
    assert user == "admin"
    assert password in printed and str(path) in printed
    assert json.loads(path.read_text(encoding="utf-8")) == {"utente": user, "password": password}
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert auth._load_credentials() == (user, password)
    assert capsys.readouterr().out == ""
