# SPDX-License-Identifier: Apache-2.0
"""Secrets as small files in a private folder (0600 on POSIX; on Windows the user profile)."""

from __future__ import annotations

import os
from pathlib import Path

PRIVATE_FILE = 0o600


class FileSecretStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def get(self, name: str) -> str | None:
        path = self._path(name)
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def set(self, name: str, value: str) -> None:
        """Write atomically, readable by the owner only."""
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value)
        os.replace(temporary, path)
        if os.name != "nt":
            path.chmod(PRIVATE_FILE)

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)

    def _path(self, name: str) -> Path:
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError(f"Invalid secret name {name!r}")
        return self.folder / name
