# SPDX-License-Identifier: Apache-2.0
"""Layout of the per-user runtime folder."""

from __future__ import annotations

import os
import stat

import pytest

from j_forecast_board.paths import RuntimePaths


def test_layout_under_the_home_folder(tmp_path):
    paths = RuntimePaths(tmp_path)
    assert paths.secrets == tmp_path / "secrets"
    assert paths.config == tmp_path / "config"
    assert paths.data == tmp_path / "data"
    assert paths.results == tmp_path / "results"
    assert paths.uploads == tmp_path / "uploads"
    assert paths.logs == tmp_path / "logs"
    assert paths.credentials == tmp_path / "secrets" / "credentials.json"
    assert paths.agent_settings == tmp_path / "secrets" / "agents.json"


def test_results_of_the_stub_model_are_kept_apart(tmp_path):
    paths = RuntimePaths(tmp_path)
    assert paths.results_for("timestral") == tmp_path / "results"
    assert paths.results_for("stub") == tmp_path / "results-stub"


def test_create_makes_every_folder(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.create()
    for folder in (
        paths.secrets,
        paths.config,
        paths.data,
        paths.results,
        paths.uploads,
        paths.logs,
    ):
        assert folder.is_dir()
    paths.create()  # idempotent


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_home_and_secrets_are_private_on_posix(tmp_path):
    paths = RuntimePaths(tmp_path / "home")
    paths.create()
    assert stat.S_IMODE(paths.home.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.secrets.stat().st_mode) == 0o700
