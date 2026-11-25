# SPDX-License-Identifier: Apache-2.0
"""Browser-side protection: security headers on every answer, and a cross-site request check.

The Content-Security-Policy allows only the app's own scripts, plus the one tiny inline script of
index.html (by its hash) that adds the trailing slash when the app is opened under a path prefix.
Styles may be inline because Plotly sets them at run time.
"""

from __future__ import annotations

import base64
import hashlib
import re
import urllib.parse
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

STATE_CHANGING = ("POST", "PUT", "PATCH", "DELETE")
SAME_SITE = ("same-origin", "none")  # "none" = typed in the address bar, a bookmark, a script


def inline_script_hashes(page: Path) -> list[str]:
    scripts = re.findall(r"<script>(.*?)</script>", page.read_text(encoding="utf-8"), re.S)
    return [base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() for s in scripts]


def content_security_policy(script_hashes: list[str]) -> str:
    scripts = " ".join(["'self'", *(f"'sha256-{h}'" for h in script_hashes)])
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src {scripts}",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self' data:",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'self'",
        ]
    )


class BrowserGuard:
    def __init__(self, index_page: Path, trust_proxy: bool):
        self._headers = {
            "Content-Security-Policy": content_security_policy(inline_script_hashes(index_page)),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "SAMEORIGIN",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        }
        self._trust_proxy = trust_proxy

    async def middleware(self, request: Request, call_next):
        if request.method in STATE_CHANGING and self.cross_site(request):
            response = JSONResponse({"error": "Cross-site request refused."}, status_code=403)
        else:
            response = await call_next(request)
        for name, value in self._headers.items():
            response.headers.setdefault(name, value)
        return response

    def cross_site(self, request: Request) -> bool:
        """A browser sending a change from another site (CSRF). Scripts without these headers pass:
        they still need to sign in."""
        site = request.headers.get("sec-fetch-site")
        if site is not None:
            return site not in SAME_SITE
        origin = request.headers.get("origin")
        if not origin or origin == "null":
            return origin == "null"
        host = request.headers.get("host", "")
        if self._trust_proxy:
            host = request.headers.get("x-forwarded-host", host)
        return urllib.parse.urlparse(origin).netloc.lower() != host.lower()
