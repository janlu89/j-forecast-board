# SPDX-License-Identifier: Apache-2.0
"""The doctor report: privacy, summary and layout, and how failures are explained."""

from __future__ import annotations

import io
import json
import ssl
from pathlib import Path

import pandas as pd

from j_forecast_board.bootstrap.doctor import app_probe, network
from j_forecast_board.bootstrap.doctor.report import (
    FAIL,
    OK,
    WARN,
    Check,
    Redactor,
    Report,
    run_check,
)

HOME = Path("/home/alice")


def report(*checks: Check) -> Report:
    return Report(mode="basic", app_version="0.1.0", commit="abc1234", checks=list(checks))


def test_redactor_hides_the_home_folder_and_user_name():
    redactor = Redactor(home=HOME, user="alice")
    value = {"path": "/home/alice/.local/share/x", "items": ["user alice", ("/home/alice",)]}
    assert redactor.value(value) == {
        "path": "~/.local/share/x",
        "items": ["user <user>", ["~"]],
    }


def test_short_user_names_are_not_replaced_inside_words():
    assert Redactor(home=HOME, user="al").text("totally fine") == "totally fine"


def test_report_counts_and_exit_code():
    good = report(Check("a", "system", OK, "fine"), Check("b", "network", WARN, "slow"))
    assert good.summary == {"ok": 1, "warn": 1, "fail": 0}
    assert good.exit_code == 0
    assert report(Check("c", "app", FAIL, "broken")).exit_code == 1


def test_report_json_has_the_documented_fields(tmp_path):
    json_path, text_path = report(Check("a", "system", OK, "at /home/alice")).write(
        tmp_path, Redactor(home=HOME, user="alice")
    )
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert list(data) == [
        "schema_version", "app_version", "commit", "created_at", "mode", "summary", "checks",
    ]  # fmt: skip
    assert data["checks"][0] == {
        "id": "a", "group": "system", "status": "ok", "message": "at ~",
        "fix": "", "details": {}, "duration_ms": 0,
    }  # fmt: skip
    assert "alice" not in text_path.read_text(encoding="utf-8")


def test_text_report_lists_failures_first_with_their_fix():
    text = report(
        Check("fine", "system", OK, "all good", fix="never shown"),
        Check("broken", "app", FAIL, "HTTP 500", fix="restart it"),
    ).to_text(Redactor(home=HOME, user="alice"))
    assert text.index("FAIL broken") < text.index("OK   fine")
    assert "fix: restart it" in text
    assert "never shown" not in text


def test_a_crashing_probe_becomes_a_failed_check():
    def probe():
        raise RuntimeError("boom")

    check = run_check("paths", "home", probe)
    assert (check.id, check.group, check.status) == ("home", "paths", FAIL)
    assert check.message == "RuntimeError: boom"


def test_certificate_errors_point_to_the_company_certificate():
    check = network._unreachable("installing packages", ssl.SSLCertVerificationError("bad"))
    assert check.status == WARN
    assert "certificate not trusted" in check.message
    assert "SSL_CERT_FILE" in check.fix


def test_timeouts_point_to_the_proxy():
    check = network._unreachable("installing packages", TimeoutError("timed out"))
    assert "timed out" in check.message
    assert "HTTPS_PROXY" in check.fix


def test_proxy_check_reports_only_whether_variables_are_set(monkeypatch):
    for name in network.PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv("https_proxy", "http://user:secret@proxy.example:8080")
    check = network._proxy_settings()
    assert check.details["HTTPS_PROXY"] == "set"
    assert "secret" not in json.dumps(check.details) + check.message


def test_synthetic_csv_has_three_stores_and_a_promo_flag():
    frame = pd.read_csv(io.BytesIO(app_probe._synthetic_csv()))
    assert list(frame.columns) == ["date", "store", "sales", "promo"]
    assert sorted(frame["store"].unique()) == ["A", "B", "C"]
    assert len(frame) == 3 * 240
    assert set(frame["promo"]) == {0, 1}


def test_only_the_session_cookie_is_kept():
    assert app_probe._session_cookie("jfb_session=1.abc; HttpOnly; Path=/") == "jfb_session=1.abc"
    assert app_probe._session_cookie("other=1; HttpOnly") == ""


def test_a_launcher_that_says_the_cli_is_missing_counts_as_not_installed(monkeypatch):
    # VS Code puts a 'copilot' shim on PATH that only prints how to install the real CLI
    from j_forecast_board.bootstrap.doctor import environment

    shim = "GitHub Copilot CLI was not found. Run copilot in a terminal to install it."
    monkeypatch.setattr(environment.shutil, "which", lambda name: "C:/VS Code/bin/copilot.EXE")
    monkeypatch.setattr(
        environment.subprocess,
        "run",
        lambda *a, **k: environment.subprocess.CompletedProcess(a, 1, stdout=shim, stderr=""),
    )
    check = environment._cli("copilot")
    assert check.status == OK
    assert check.message == "copilot: not installed (optional; only a launcher is on PATH)"
    assert check.details == {"found": False, "launcher": "C:/VS Code/bin/copilot.EXE"}
