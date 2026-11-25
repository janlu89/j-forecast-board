# SPDX-License-Identifier: Apache-2.0
"""The doctor's app probe against the real app: every route it calls must exist and answer."""

from __future__ import annotations

import shutil

from j_forecast_board.bootstrap import settings
from j_forecast_board.bootstrap.doctor.app_probe import app_checks
from j_forecast_board.bootstrap.doctor.report import FAIL
from j_forecast_board.bootstrap.paths import RuntimePaths


def test_the_doctor_probe_passes_on_the_stub_model(tmp_path, repo_root, monkeypatch):
    home = tmp_path / "home"
    shutil.copytree(repo_root / "tests" / "golden" / "fixtures" / "data", home / "data")
    probe_settings = settings.Settings(home=home, model="stub", offline=True)
    monkeypatch.setattr(settings, "current", lambda: probe_settings)
    checks = app_checks(RuntimePaths(home), progress=lambda message: None)
    failed = [f"{c.id}: {c.message}" for c in checks if c.status == FAIL]
    assert failed == []
    assert len(checks) > 25
