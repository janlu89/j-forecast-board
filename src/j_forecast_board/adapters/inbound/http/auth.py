# SPDX-License-Identifier: Apache-2.0
"""Sign-in: a login page sets a signed session cookie; HTTP Basic auth is accepted for scripts.

In-app browsers (mobile apps, chat clients) often never show the Basic-auth popup, hence the page.
The app may be served under a path prefix (e.g. /board), so every URL produced here is relative.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import html
import re
import secrets
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ....application.credentials import Credentials

COOKIE = "jfb_session"
SESSION_DAYS = 30
INTERNAL_HEADER = "x-internal-token"
PUBLIC_PATHS = ("/login", "/logout")
FAILED_LOGIN_DELAY = 1.0  # seconds: slows down guessing
_NEXT_OK = re.compile(r"^[A-Za-z0-9_./-]{0,200}$")
_PAGE = (Path(__file__).parent / "templates" / "login.html").read_text(encoding="utf-8")


class Authenticator:
    """Who may use the app: a signed-in browser, a Basic-auth client, or a local helper."""

    def __init__(self, credentials: Credentials, enabled: bool):
        self.credentials = credentials
        self.enabled = enabled
        # Random per process: lets local helpers (the assistant's tool server) call the API.
        self.internal_token = secrets.token_urlsafe(32)

    def authorized(self, request: Request) -> bool:
        if secrets.compare_digest(request.headers.get(INTERNAL_HEADER, ""), self.internal_token):
            return True
        if self.credentials.session_valid(request.cookies.get(COOKIE)):
            return True
        return self._basic_ok(request.headers.get("authorization", ""))

    def _basic_ok(self, header: str) -> bool:
        if not header.lower().startswith("basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        except (binascii.Error, ValueError):
            return False
        user, _, password = decoded.partition(":")
        return self.credentials.check(user, password)

    async def middleware(self, request: Request, call_next):
        path = request.url.path
        if not self.enabled or path in PUBLIC_PATHS or self.authorized(request):
            return await call_next(request)
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            target = safe_next(path)
            query = f"?next={target}" if target else ""
            return RedirectResponse(f"{to_root(path)}login{query}", status_code=303)
        return JSONResponse({"error": "Login required"}, status_code=401)

    # ------------------------------------------------------------------ pages
    def login_page(self, request: Request) -> HTMLResponse:
        error = ""
        if request.query_params.get("e"):
            error = '<div class="err" role="alert">Wrong username or password.</div>'
        target = html.escape(safe_next(request.query_params.get("next")))
        page = _PAGE.replace("%NEXT%", target).replace("%ERROR%", error)
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    async def login_submit(self, request: Request) -> Response:
        form = await request.form()
        target = safe_next(str(form.get("next", "")))
        user, password = str(form.get("username", "")).strip(), str(form.get("password", ""))
        if not self.credentials.check(user, password):
            await asyncio.sleep(FAILED_LOGIN_DELAY)
            query = f"&next={target}" if target else ""
            return RedirectResponse(f"login?e=1{query}", status_code=303)
        expires = int(time.time()) + SESSION_DAYS * 86400
        response = RedirectResponse(target or "./", status_code=303)
        https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        # No Path attribute: the cookie stays scoped to the prefix the app is served under.
        response.set_cookie(
            COOKIE,
            self.credentials.session(expires),
            max_age=SESSION_DAYS * 86400,
            httponly=True,
            samesite="lax",
            secure=https,
            path=None,
        )
        return response

    @staticmethod
    def logout() -> Response:
        response = RedirectResponse("login", status_code=303)
        response.delete_cookie(COOKIE, path=None)
        return response


def to_root(path: str) -> str:
    """Relative prefix from `path` back to the app root ('' for '/', '../' for '/static/x')."""
    return "../" * max(0, path.count("/") - 1)


def safe_next(value: str | None) -> str:
    """A redirect target inside the app, or '' (never another site)."""
    target = (value or "").lstrip("/")
    return target if _NEXT_OK.match(target) and ".." not in target and "//" not in target else ""
