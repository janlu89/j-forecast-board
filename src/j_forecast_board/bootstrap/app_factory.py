# SPDX-License-Identifier: Apache-2.0
"""Build the web app from the settings of this process (used by `serve` and the doctor)."""

from __future__ import annotations

from fastapi import FastAPI

from ..adapters.inbound.http.app import create_app as create_http_app
from . import settings
from .container import Container, build


def create_app(container: Container | None = None) -> FastAPI:
    container = container or build(settings.current())
    app = create_http_app(container, on_start=container.start)
    app.state.container = container
    return app
