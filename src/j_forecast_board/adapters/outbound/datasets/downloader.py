# SPDX-License-Identifier: Apache-2.0
"""Download public dataset files once into the runtime data folder."""

from __future__ import annotations

import os
import time
import urllib.request
from pathlib import Path

ATTEMPTS = 5
TIMEOUT_SECONDS = 120
USER_AGENT = "j-forecast-board/0.1"


class Downloader:
    def __init__(self, folder: Path, offline: bool):
        self.folder = Path(folder)
        self.offline = offline

    def fetch(self, url: str, name: str) -> bytes:
        """The file's bytes: from the data folder, else downloaded (with retries)
        and saved there."""
        path = self.folder / name
        if path.exists():
            return path.read_bytes()
        if self.offline:
            raise RuntimeError(f"Offline mode (JFB_OFFLINE=1): {name} has not been downloaded yet.")
        path.parent.mkdir(parents=True, exist_ok=True)
        last = None
        for _ in range(ATTEMPTS):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                    content = response.read()
                _write_atomically(path, content)
                return content
            except Exception as error:  # network errors come in many types; retry them all
                last = error
                time.sleep(2)
        raise RuntimeError(f"Download failed for {url}: {last}")


def _write_atomically(path: Path, content: bytes) -> None:
    """A download cut by a crash must not look like a complete file at the next start."""
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(content)
    os.replace(temporary, path)
