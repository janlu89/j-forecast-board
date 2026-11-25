# SPDX-License-Identifier: Apache-2.0
"""`python -m j_forecast_board doctor`: check this PC and write a shareable report.

Modes: `basic` (system, Python, packages, folders, network), `no-model` (also starts the app on
the stub model and calls every route), `with-model` (also loads a real Timestral model once).
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import time
from pathlib import Path

from .. import settings
from ..paths import RuntimePaths
from .app_probe import app_checks
from .environment import environment_checks
from .network import network_checks
from .report import FAIL, OK, Check, Redactor, Report, run_check

MODES = ("basic", "no-model", "with-model")
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def prepare_environment(mode: str) -> None:
    """Before the settings are read: the app probe always uses the stub and the sign-in page."""
    if mode != "basic":
        os.environ["JFB_MODEL"] = "stub"
        os.environ["JFB_AUTH"] = "on"


def run(mode: str, out_dir: Path) -> int:
    config = settings.current()
    paths = RuntimePaths(config.home)
    report = Report(mode=mode, app_version=_app_version(), commit=_commit())
    _say("Checking the system, Python, packages and folders...")
    report.checks += environment_checks(config, paths)
    _say("Checking the network...")
    report.checks += network_checks()
    if mode != "basic":
        report.checks += app_checks(paths, _say)
    if mode == "with-model":
        _say(f"Loading Timestral-{config.default_model_size} and running one forecast...")
        report.checks.append(run_check("model", "forecast", lambda: _real_forecast(config)))
    redactor = Redactor()
    json_path, text_path = report.write(out_dir, redactor)
    print()
    print(report.to_text(redactor))
    print(f"Report written to {text_path} and {json_path.name}.")
    return report.exit_code


def _real_forecast(config: settings.Settings) -> Check:
    import numpy as np
    from timestral import TimestralForecaster

    started = time.perf_counter()
    model = TimestralForecaster.from_pretrained(
        config.default_model_repo, device="cpu", local_files_only=config.offline
    )
    loaded = time.perf_counter()
    steps = np.arange(512)
    series = 100 + 10 * np.sin(2 * np.pi * steps / 7) + 0.05 * steps
    forecast = model.forecast(series[None, :], prediction_length=28)
    finished = time.perf_counter()
    shape = list(np.asarray(forecast.quantiles).shape)
    details = dict(
        load_seconds=round(loaded - started, 2), forecast_seconds=round(finished - loaded, 2)
    )
    message = (
        f"Timestral-{config.default_model_size} loaded in {details['load_seconds']} s, "
        f"one 28-step forecast in {details['forecast_seconds']} s (output {shape})"
    )
    return Check("", "", OK, message, details=details)


def _app_version() -> str:
    try:
        return importlib.metadata.version("j-forecast-board")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _commit() -> str:
    """The commit of this copy: COMMIT file of an exported copy, else git, else unknown."""
    stamp = PROJECT_ROOT / "COMMIT"
    if stamp.is_file():
        return stamp.read_text(encoding="utf-8").strip()[:40]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=10, check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _say(message: str) -> None:
    print(message, flush=True)


__all__ = ["FAIL", "MODES", "OK", "prepare_environment", "run"]
