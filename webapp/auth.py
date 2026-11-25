"""Access protection for the demo when it is published on the internet (Tailscale Funnel).

A login page sets a signed session cookie; HTTP Basic auth is still accepted (curl, scripts).
In-app browsers (mobile apps, chat clients) often never show the Basic-auth popup, hence the page.
Credentials live in ../accesso_demo.json (created on first start with a random password).
The app may be served under a path prefix (e.g. /timestral), so every URL produced here is relative.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

CREDENTIALS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "accesso_demo.json")
COOKIE = "timestral_session"
SESSION_DAYS = 30
# Random per process: lets local helpers (the chat's tool server) call the API without the password.
INTERNAL_TOKEN = secrets.token_urlsafe(32)
INTERNAL_HEADER = "x-internal-token"
_NEXT_OK = re.compile(r"^[A-Za-z0-9_./-]{0,200}$")


def _load_credentials() -> tuple[str, str]:
    if not os.path.exists(CREDENTIALS):
        with open(CREDENTIALS, "w", encoding="utf-8") as f:
            json.dump({"utente": "demo", "password": secrets.token_urlsafe(12)}, f, indent=1)
    with open(CREDENTIALS, encoding="utf-8") as f:
        c = json.load(f)
    return c["utente"], c["password"]


USER, PASSWORD = _load_credentials()
# Changing the password invalidates every session.
_KEY = hashlib.sha256(f"{USER}:{PASSWORD}:timestral-session".encode()).digest()


def _sign(exp: int) -> str:
    return hmac.new(_KEY, str(exp).encode(), hashlib.sha256).hexdigest()


def _session_ok(value: str | None) -> bool:
    if not value or "." not in value:
        return False
    exp, _, sig = value.partition(".")
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, _sign(int(exp)))


def _credentials_ok(user: str, pw: str) -> bool:
    # Evaluate both comparisons so the timing does not reveal which one failed.
    u = secrets.compare_digest(user.encode(), USER.encode())
    p = secrets.compare_digest(pw.encode(), PASSWORD.encode())
    return u and p


def _basic_ok(header: str) -> bool:
    if not header.lower().startswith("basic "):
        return False
    try:
        user, _, pw = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except Exception:
        return False
    return _credentials_ok(user, pw)


def authorized(request: Request) -> bool:
    if secrets.compare_digest(request.headers.get(INTERNAL_HEADER, ""), INTERNAL_TOKEN):
        return True
    return _session_ok(request.cookies.get(COOKIE)) or _basic_ok(request.headers.get("authorization", ""))


def _to_root(path: str) -> str:
    """Relative prefix from `path` back to the app root ('' for '/', '../' for '/static/x', ...)."""
    return "../" * max(0, path.count("/") - 1)


def _safe_next(value: str | None) -> str:
    v = (value or "").lstrip("/")
    return v if _NEXT_OK.match(v) and ".." not in v and "//" not in v else ""


async def middleware(request: Request, call_next):
    path = request.url.path
    if path in ("/login", "/logout") or authorized(request):
        return await call_next(request)
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        nxt = _safe_next(path)
        return RedirectResponse(f"{_to_root(path)}login" + (f"?next={nxt}" if nxt else ""), status_code=303)
    return JSONResponse({"error": "Login required"}, status_code=401)


# ----------------------------------------------------------------------------- pages
_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Timestral demo · Sign in</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='3' fill='%230b0d12'/%3E%3Cpath d='M2 11 L6 7 L9 9 L14 3' stroke='%23ff7a1a' stroke-width='2' fill='none'/%3E%3C/svg%3E">
<style>
:root{--bg:#0b0d12;--card:#141821;--line:#2a3040;--fg:#e6e8ee;--muted:#8a90a2;--accent:#ff7a1a;--bad:#f87171}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);
font:15px/1.5 Inter,"Segoe UI",system-ui,sans-serif;padding:16px}
form{width:100%;max-width:360px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:26px}
h1{font-size:20px;margin:0 0 4px}h1 span{color:var(--accent)}p{color:var(--muted);margin:0 0 18px;font-size:13.5px}
label{display:block;font-size:13px;color:var(--muted);margin:12px 0 4px}
input{width:100%;padding:10px 12px;border-radius:8px;border:1px solid var(--line);background:#0f1218;color:var(--fg);font-size:15px}
input:focus{outline:2px solid var(--accent);outline-offset:1px}
button{width:100%;margin-top:20px;padding:11px;border:0;border-radius:8px;background:var(--accent);color:#111;font-weight:700;font-size:15px;cursor:pointer}
.err{color:var(--bad);margin:12px 0 0;font-size:13.5px}
</style></head><body>
<form method="post" action="login">
<h1><span>Timestral</span> demo</h1><p>Time-series forecasting with Mistral's open model. Please sign in.</p>
<label for="u">Username</label><input id="u" name="username" autocomplete="username" autocapitalize="none" required autofocus>
<label for="p">Password</label><input id="p" name="password" type="password" autocomplete="current-password" required>
<input type="hidden" name="next" value="%NEXT%">%ERROR%
<button type="submit">Sign in</button>
</form></body></html>"""


def login_page(request: Request) -> HTMLResponse:
    err = '<div class="err" role="alert">Wrong username or password.</div>' if request.query_params.get("e") else ""
    nxt = html.escape(_safe_next(request.query_params.get("next")))
    return HTMLResponse(_PAGE.replace("%NEXT%", nxt).replace("%ERROR%", err), headers={"Cache-Control": "no-store"})


async def login_submit(request: Request) -> Response:
    form = await request.form()
    nxt = _safe_next(str(form.get("next", "")))
    if not _credentials_ok(str(form.get("username", "")).strip(), str(form.get("password", ""))):
        await asyncio.sleep(1.0)  # slow down guessing
        return RedirectResponse("login?e=1" + (f"&next={nxt}" if nxt else ""), status_code=303)
    exp = int(time.time()) + SESSION_DAYS * 86400
    res = RedirectResponse(nxt or "./", status_code=303)
    https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    # No Path attribute: the cookie stays scoped to the prefix the app is served under (e.g. /timestral).
    res.set_cookie(COOKIE, f"{exp}.{_sign(exp)}", max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                   secure=https, path=None)
    return res


def logout() -> Response:
    res = RedirectResponse("login", status_code=303)
    res.delete_cookie(COOKIE, path=None)
    return res
