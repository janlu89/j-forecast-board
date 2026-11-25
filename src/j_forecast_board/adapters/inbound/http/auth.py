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
import threading
import time
from collections import defaultdict
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ....application.credentials import Credentials

COOKIE = "jfb_session"
SESSION_DAYS = 30
PUBLIC_PATHS = ("/login", "/logout")
INTERNAL_PREFIX = "/internal/"  # tool calls of a CLI assistant: authorised by their own token
FAILED_LOGIN_DELAY = 1.0  # seconds: slows down guessing
MAX_FAILURES = 5
LOCKOUT_SECONDS = 60
FORWARDING_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip", "tailscale-user-login")
LOOPBACK = ("127.0.0.1", "::1", "localhost")
_NEXT_OK = re.compile(r"^[A-Za-z0-9_./-]{0,200}$")
_PAGE = (Path(__file__).parent / "templates" / "login.html").read_text(encoding="utf-8")


class Authenticator:
    """Who may use the app: a signed-in browser, a Basic-auth client, or a local helper."""

    def __init__(self, credentials: Credentials, enabled: bool, audit=None):
        self.credentials = credentials
        self.enabled = enabled
        self._audit = audit
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def authorized(self, request: Request) -> bool:
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
        if path.startswith(INTERNAL_PREFIX):
            if not is_direct_local_call(request):
                return JSONResponse({"error": "Not available here."}, status_code=403)
            return await call_next(request)
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
        if request.query_params.get("e") == "2":
            error = '<div class="err" role="alert">Too many failed attempts: wait a minute.</div>'
        elif request.query_params.get("e"):
            error = '<div class="err" role="alert">Wrong username or password.</div>'
        target = html.escape(safe_next(request.query_params.get("next")))
        page = _PAGE.replace("%NEXT%", target).replace("%ERROR%", error)
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    async def login_submit(self, request: Request) -> Response:
        form = await request.form()
        target = safe_next(str(form.get("next", "")))
        user, password = str(form.get("username", "")).strip(), str(form.get("password", ""))
        client = request.client.host if request.client else "unknown"
        query = f"&next={target}" if target else ""
        if self._locked(client):
            return RedirectResponse(f"login?e=2{query}", status_code=303)
        if not self.credentials.check(user, password):
            locked = self._failed(client)
            self._record("lockout" if locked else "login_failed", client=client)
            await asyncio.sleep(FAILED_LOGIN_DELAY)
            return RedirectResponse(f"login?e={2 if locked else 1}{query}", status_code=303)
        self._succeeded(client)
        self._record("login_ok", client=client)
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

    # ------------------------------------------------------------------ lock-out
    def _locked(self, client: str) -> bool:
        with self._lock:
            return self._locked_until.get(client, 0) > time.monotonic()

    def _failed(self, client: str) -> bool:
        """Count a failure; True when the client is now locked out."""
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._failures[client] if now - t < LOCKOUT_SECONDS] + [now]
            self._failures[client] = recent
            if len(recent) >= MAX_FAILURES:
                self._locked_until[client] = now + LOCKOUT_SECONDS
                self._failures[client] = []
                return True
        return False

    def _succeeded(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)
            self._locked_until.pop(client, None)

    def _record(self, event: str, **fields) -> None:
        if self._audit is not None:
            self._audit.record(event, **fields)

    @staticmethod
    def logout() -> Response:
        response = RedirectResponse("login", status_code=303)
        response.delete_cookie(COOKIE, path=None)
        return response


def is_direct_local_call(request: Request) -> bool:
    """A request made on this PC straight to the app, not relayed by a proxy."""
    if any(name in request.headers for name in FORWARDING_HEADERS):
        return False
    client = request.client.host if request.client else ""
    server = (request.scope.get("server") or ("", 0))[0]
    return client in LOOPBACK or client == server


def to_root(path: str) -> str:
    """Relative prefix from `path` back to the app root ('' for '/', '../' for '/static/x')."""
    return "../" * max(0, path.count("/") - 1)


def safe_next(value: str | None) -> str:
    """A redirect target inside the app, or '' (never another site)."""
    target = (value or "").lstrip("/")
    return target if _NEXT_OK.match(target) and ".." not in target and "//" not in target else ""
