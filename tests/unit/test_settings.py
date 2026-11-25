# SPDX-License-Identifier: Apache-2.0
"""Settings read from JFB_* environment variables, and the per-user runtime folder."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

import pytest

from j_forecast_board.bootstrap.settings import Settings, SettingsError, default_home


def test_defaults_without_any_variable(tmp_path):
    settings = Settings.from_env({"JFB_HOME": str(tmp_path)})
    assert settings.home == tmp_path
    assert (settings.host, settings.port) == ("127.0.0.1", 8000)
    assert settings.model == "timestral"
    assert settings.default_model_size == "28M"
    assert settings.default_model_repo == "mistralai/Timestral-28M"
    assert settings.offline is False
    assert settings.auth == "on"
    assert settings.root_path == ""
    assert settings.trust_proxy is False
    assert settings.background_eval is True
    assert settings.chat_timeout == 240
    assert settings.log_level == "info"


def test_every_variable_is_read(tmp_path):
    env = {
        "JFB_HOME": str(tmp_path),
        "JFB_HOST": "0.0.0.0",
        "JFB_PORT": "8010",
        "JFB_MODEL": "stub",
        "JFB_DEFAULT_MODEL_SIZE": "5M",
        "JFB_OFFLINE": "1",
        "JFB_AUTH": "on",
        "JFB_ROOT_PATH": "/board/",
        "JFB_TRUST_PROXY": "true",
        "JFB_BACKGROUND_EVAL": "0",
        "JFB_CHAT_TIMEOUT": "60",
        "JFB_LOG_LEVEL": "DEBUG",
    }
    settings = Settings.from_env(env)
    assert (settings.host, settings.port) == ("0.0.0.0", 8010)
    assert settings.model == "stub"
    assert settings.default_model_repo == "mistralai/Timestral-5M"
    assert settings.offline and settings.trust_proxy
    assert settings.background_eval is False
    assert settings.root_path == "/board"
    assert settings.chat_timeout == 60
    assert settings.log_level == "debug"


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("JFB_PORT", "eighty", "JFB_PORT"),
        ("JFB_PORT", "70000", "JFB_PORT"),
        ("JFB_MODEL", "chronos", "JFB_MODEL"),
        ("JFB_DEFAULT_MODEL_SIZE", "1B", "JFB_DEFAULT_MODEL_SIZE"),
        ("JFB_OFFLINE", "maybe", "JFB_OFFLINE"),
        ("JFB_AUTH", "auto", "JFB_AUTH"),
        ("JFB_ROOT_PATH", "board", "JFB_ROOT_PATH"),
        ("JFB_CHAT_TIMEOUT", "0", "JFB_CHAT_TIMEOUT"),
        ("JFB_LOG_LEVEL", "loud", "JFB_LOG_LEVEL"),
    ],
)
def test_invalid_values_name_the_variable(tmp_path, name, value, message):
    with pytest.raises(SettingsError, match=message):
        Settings.from_env({"JFB_HOME": str(tmp_path), name: value})


def test_authentication_cannot_be_off_on_a_network_address(tmp_path):
    env = {"JFB_HOME": str(tmp_path), "JFB_AUTH": "off", "JFB_HOST": "0.0.0.0"}
    with pytest.raises(SettingsError, match="JFB_AUTH=off"):
        Settings.from_env(env)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_authentication_can_be_off_on_loopback(tmp_path, host):
    env = {"JFB_HOME": str(tmp_path), "JFB_AUTH": "off", "JFB_HOST": host}
    assert Settings.from_env(env).auth == "off"


def test_with_binding_rechecks_the_exposure_rule(tmp_path):
    settings = Settings.from_env({"JFB_HOME": str(tmp_path), "JFB_AUTH": "off"})
    assert settings.with_binding("127.0.0.1", 9000).port == 9000
    with pytest.raises(SettingsError, match="JFB_AUTH=off"):
        settings.with_binding("192.168.1.5", None)


def test_default_home_on_windows_is_in_local_app_data():
    env = {"LOCALAPPDATA": r"C:\Users\someone\AppData\Local"}
    home = default_home(env, system="Windows", user_home=Path("unused"))
    assert PureWindowsPath(home) == PureWindowsPath(
        r"C:\Users\someone\AppData\Local\JForecastBoard"
    )


def test_default_home_on_linux_follows_xdg(tmp_path):
    assert default_home({"XDG_DATA_HOME": str(tmp_path)}, system="Linux", user_home=Path("/x")) == (
        tmp_path / "j-forecast-board"
    )
    assert default_home({}, system="Linux", user_home=tmp_path) == (
        tmp_path / ".local" / "share" / "j-forecast-board"
    )


def test_upload_limit_is_configurable(tmp_path):
    assert Settings.from_env({"JFB_HOME": str(tmp_path)}).max_upload_mb == 200
    assert (
        Settings.from_env({"JFB_HOME": str(tmp_path), "JFB_MAX_UPLOAD_MB": "20"}).max_upload_mb
        == 20
    )
    with pytest.raises(SettingsError, match="JFB_MAX_UPLOAD_MB"):
        Settings.from_env({"JFB_HOME": str(tmp_path), "JFB_MAX_UPLOAD_MB": "0"})


def test_purge_deletes_the_runtime_folder(tmp_path, monkeypatch):
    from j_forecast_board.bootstrap import cli, settings

    home = tmp_path / "home"
    (home / "secrets").mkdir(parents=True)
    (home / "secrets" / "agent-keys.json").write_text("{}")
    monkeypatch.setattr(settings, "current", lambda: Settings(home=home))
    assert cli.main(["purge", "--yes"]) == 0
    assert not home.exists()


def test_a_broken_policy_file_stops_the_start(tmp_path, monkeypatch, capsys):
    from j_forecast_board.bootstrap import cli, settings

    policy = tmp_path / "policy.json"
    policy.write_text('{"allow_external_ai": "no"}', encoding="utf-8")
    monkeypatch.setattr(settings, "current", lambda: Settings(home=tmp_path, policy_file=policy))
    assert cli.main(["agent", "list"]) == 2
    assert "allow_external_ai must be true or false" in capsys.readouterr().err
