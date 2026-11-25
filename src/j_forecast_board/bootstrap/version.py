# SPDX-License-Identifier: Apache-2.0
"""The installed version of the app."""

from __future__ import annotations

import importlib.metadata


def app_version() -> str:
    try:
        return importlib.metadata.version("j-forecast-board")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"
