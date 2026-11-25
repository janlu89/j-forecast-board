# SPDX-License-Identifier: Apache-2.0
"""The page, its assets and the manuals. Every URL is relative: the app may live under a prefix."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

WEB = Path(__file__).resolve().parents[3] / "static"
VERSIONED = ("style.css",)
REVALIDATE = (".js", ".css", ".html")  # the app's own code: always check for a newer copy


def install(app: FastAPI) -> None:
    @app.get("/manual")
    def manual():
        return RedirectResponse("static/manual/index.html")

    @app.get("/manual/en")
    def manual_en():
        return RedirectResponse("../static/manual/en.html")

    @app.get("/")
    def index():
        return HTMLResponse(_index_page(), headers={"Cache-Control": "no-store"})

    app.mount("/static", RevalidatingFiles(directory=WEB), name="static")


class RevalidatingFiles(StaticFiles):
    """ES modules cannot carry a version in their import URLs: the browser revalidates them
    (cheap 304 answers), while the vendored Plotly may be cached for a day."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        path = str(args[0]) if args else ""
        if "/vendor/" in path.replace("\\", "/"):
            response.headers["Cache-Control"] = "public, max-age=86400"
        elif path.endswith(REVALIDATE):
            response.headers["Cache-Control"] = "no-cache"
        return response


def _index_page() -> str:
    """The page with its own CSS/JS versioned by modification time, so a browser never runs a
    stale copy after an update."""
    page = (WEB / "index.html").read_text(encoding="utf-8")
    for name in VERSIONED:
        version = int((WEB / name).stat().st_mtime)
        page = page.replace(f'"static/{name}"', f'"static/{name}?v={version}"')
    return page
