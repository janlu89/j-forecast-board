# SPDX-License-Identifier: Apache-2.0
"""Where runtime files live inside the per-user home folder (see docs/configuration.md)."""

from __future__ import annotations

import functools
import os
from pathlib import Path

from . import settings

_PRIVATE_FOLDER = 0o700


class RuntimePaths:
    """Folders and files under JFB_HOME. Nothing here is ever inside the source tree."""

    def __init__(self, home: Path):
        self.home = Path(home)
        self.secrets = self.home / "secrets"
        self.config = self.home / "config"
        self.data = self.home / "data"
        self.results = self.home / "results"
        self.uploads = self.home / "uploads"
        self.logs = self.home / "logs"
        self.credentials = self.secrets / "credentials.json"
        self.agent_settings = self.secrets / "agents.json"

    def results_for(self, model_backend: str) -> Path:
        """Cached backtests per model backend, so stub results never pass for real ones."""
        return (
            self.results if model_backend == "timestral" else self.home / f"results-{model_backend}"
        )

    def create(self) -> None:
        """Create every folder. On Windows the user profile protects them; on POSIX, 0700."""
        for folder in (self.secrets, self.config, self.data, self.results, self.uploads, self.logs):
            folder.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.home.chmod(_PRIVATE_FOLDER)
            self.secrets.chmod(_PRIVATE_FOLDER)


@functools.cache
def current() -> RuntimePaths:
    """The runtime folders of this process, created on first use."""
    paths = RuntimePaths(settings.current().home)
    paths.create()
    return paths
