# SPDX-License-Identifier: Apache-2.0
"""Application settings, read once from JFB_* environment variables.

Every variable is documented in docs/configuration.md. Invalid values stop the start with a
message that names the variable, instead of failing later in an unrelated place.
"""

from __future__ import annotations

import dataclasses
import functools
import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

MODEL_BACKENDS = ("timestral", "stub")
MODEL_SIZES = ("5M", "28M", "123M", "209M")
AUTH_MODES = ("on", "off")
LOG_LEVELS = ("critical", "error", "warning", "info", "debug", "trace")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off", "")


class SettingsError(ValueError):
    """A JFB_* variable has a value the app cannot use."""


@dataclass(frozen=True)
class Settings:
    home: Path
    host: str = "127.0.0.1"
    port: int = 8000
    model: str = "timestral"
    default_model_size: str = "28M"
    offline: bool = False
    auth: str = "on"
    root_path: str = ""
    trust_proxy: bool = False
    background_eval: bool = True
    chat_timeout: int = 240
    log_level: str = "info"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        reader = _Reader(env)
        settings = cls(
            home=Path(env["JFB_HOME"]) if env.get("JFB_HOME") else default_home(env),
            host=reader.text("JFB_HOST", "127.0.0.1"),
            port=reader.integer("JFB_PORT", 8000, minimum=1, maximum=65535),
            model=reader.choice("JFB_MODEL", "timestral", MODEL_BACKENDS),
            default_model_size=reader.choice("JFB_DEFAULT_MODEL_SIZE", "28M", MODEL_SIZES),
            offline=reader.flag("JFB_OFFLINE", False),
            auth=reader.choice("JFB_AUTH", "on", AUTH_MODES),
            root_path=reader.root_path("JFB_ROOT_PATH"),
            trust_proxy=reader.flag("JFB_TRUST_PROXY", False),
            background_eval=reader.flag("JFB_BACKGROUND_EVAL", True),
            chat_timeout=reader.integer("JFB_CHAT_TIMEOUT", 240, minimum=1, maximum=3600),
            log_level=reader.choice("JFB_LOG_LEVEL", "info", LOG_LEVELS),
        )
        settings.check_exposure()
        return settings

    @property
    def default_model_repo(self) -> str:
        return f"mistralai/Timestral-{self.default_model_size}"

    def with_binding(self, host: str | None, port: int | None) -> Settings:
        """The same settings bound to another address (command line options win over variables)."""
        bound = dataclasses.replace(self, host=host or self.host, port=port or self.port)
        bound.check_exposure()
        return bound

    def check_exposure(self) -> None:
        """Without authentication the app may only listen on this PC."""
        if self.auth == "off" and self.host not in LOOPBACK_HOSTS:
            raise SettingsError(
                f"JFB_AUTH=off is only allowed on this PC (127.0.0.1), not on {self.host}: "
                "anyone on the network could use the app."
            )


def default_home(
    env: Mapping[str, str], system: str | None = None, user_home: Path | None = None
) -> Path:
    """Per-user folder for runtime files, outside the code (Windows: Local AppData)."""
    system = system or platform.system()
    user_home = user_home or Path.home()
    if system == "Windows":
        base = env.get("LOCALAPPDATA") or str(user_home / "AppData" / "Local")
        return Path(base) / "JForecastBoard"
    base = env.get("XDG_DATA_HOME") or str(user_home / ".local" / "share")
    return Path(base) / "j-forecast-board"


@functools.cache
def current() -> Settings:
    """The settings of this process, read from the environment on first use."""
    return Settings.from_env(os.environ)


class _Reader:
    def __init__(self, env: Mapping[str, str]):
        self._env = env

    def _raw(self, name: str) -> str | None:
        value = self._env.get(name)
        return None if value is None else value.strip()

    def text(self, name: str, default: str) -> str:
        return self._raw(name) or default

    def integer(self, name: str, default: int, minimum: int, maximum: int) -> int:
        raw = self._raw(name)
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            raise SettingsError(f"{name} must be a whole number, not '{raw}'.") from None
        if not minimum <= value <= maximum:
            raise SettingsError(f"{name} must be between {minimum} and {maximum}, not {value}.")
        return value

    def flag(self, name: str, default: bool) -> bool:
        raw = self._raw(name)
        if raw is None:
            return default
        if raw.lower() in _TRUE:
            return True
        if raw.lower() in _FALSE:
            return False
        raise SettingsError(f"{name} must be 1 or 0, not '{raw}'.")

    def choice(self, name: str, default: str, allowed: tuple[str, ...]) -> str:
        raw = self._raw(name)
        if not raw:
            return default
        value = raw.lower() if name == "JFB_LOG_LEVEL" else raw
        if value not in allowed:
            raise SettingsError(f"{name} must be one of {', '.join(allowed)}, not '{raw}'.")
        return value

    def root_path(self, name: str) -> str:
        raw = self._raw(name) or ""
        if raw and not raw.startswith("/"):
            raise SettingsError(f"{name} must start with '/', for example /board, not '{raw}'.")
        return raw.rstrip("/")
