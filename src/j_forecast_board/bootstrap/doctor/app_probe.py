# SPDX-License-Identifier: Apache-2.0
"""Start the app in this process and call every route once (doctor --no-model / --with-model).

The probe uploads a small synthetic CSV and works on it, so it does not depend on the built-in
datasets being downloadable. Only status codes and timings go into the report, never values.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
import urllib.parse
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from ..paths import RuntimePaths
from .report import FAIL, OK, WARN, Check, run_check

BUILT_IN_DATASETS = ("rossmann", "bike", "energy", "passengers", "germany", "melbourne")
START_TIMEOUT = 900  # the first start downloads the public datasets
EVALUATION_TIMEOUT = 600
DEFAULT_VARIANT = "mistralai/Timestral-28M|cov|missing"


@dataclass
class Answer:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body or b"null")

    def error(self) -> str:
        try:
            return str(self.json().get("error", ""))[:200]
        except (ValueError, AttributeError):
            return self.body[:200].decode("utf-8", "replace")


class LocalApp:
    """The app served by uvicorn on a free loopback port, in a background thread."""

    def __init__(self):
        self.port = _free_port()
        self._server = None
        self._cookie = ""
        self.container = None

    def start(self, progress: Callable[[str], None]) -> None:
        import uvicorn

        from .. import settings
        from ..app_factory import create_app
        from ..container import build

        self.container = build(settings.current())
        app = create_app(self.container)
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        threading.Thread(target=self._server.run, name="doctor-app", daemon=True).start()
        progress("Starting the app (the first start downloads the public datasets)...")
        deadline = time.monotonic() + START_TIMEOUT
        while not self._server.started:
            if time.monotonic() > deadline or self._server.should_exit:
                raise RuntimeError("the app did not start in time")
            time.sleep(0.2)

    def use_cookie(self, cookie: str) -> None:
        self._cookie = cookie

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True

    def call(self, method: str, path: str, body=None, form=None, upload=None, html=False) -> Answer:
        headers = {"Accept": "text/html" if html else "application/json"}
        if self._cookie:
            headers["Cookie"] = self._cookie
        payload = None
        if body is not None:
            payload, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif form is not None:
            payload = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif upload is not None:
            payload, headers["Content-Type"] = _multipart(*upload)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=300)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            answer = Answer(response.status, dict(response.getheaders()), response.read())
        finally:
            connection.close()
        session = _session_cookie(answer.headers.get("set-cookie", ""))
        if session:
            self._cookie = session
        return answer


def app_checks(paths: RuntimePaths, progress: Callable[[str], None]) -> list[Check]:
    app = LocalApp()
    started = run_check("app", "start", lambda: _start(app, progress))
    if started.status == FAIL:
        return [started]
    try:
        return [started, *_route_checks(app, paths, progress)]
    finally:
        app.stop()


def _start(app: LocalApp, progress) -> Check:
    app.start(progress)
    return Check("", "", OK, f"the app started on a free local port ({app.port})")


def _route_checks(app: LocalApp, paths: RuntimePaths, progress) -> list[Check]:
    checks = [
        _route(app, "GET /login", "GET", "/login", expect=200),
        run_check("app", "POST /login", lambda: _wrong_password(app)),
        run_check("app", "session", lambda: _session(app)),
        _route(app, "GET /", "GET", "/", expect=200, html=True),
        _route(app, "GET /static/js/main.js", "GET", "/static/js/main.js", expect=200),
        _route(app, "GET /static/vendor/plotly.min.js", "GET", "/static/vendor/plotly.min.js", 200),
        _route(app, "GET /manual", "GET", "/manual", expect=307),
        _route(app, "GET /static/manual/index.html", "GET", "/static/manual/index.html", 200),
        run_check("app", "GET /api/datasets", lambda: _datasets(app)),
        _route(app, "GET /api/models", "GET", "/api/models", expect=200),
        _route(app, "GET /api/system", "GET", "/api/system", expect=200),
        _route(app, "GET /api/assistant", "GET", "/api/assistant", expect=200),
        _route(
            app,
            "POST /api/chat (off until set up)",
            "POST",
            "/api/chat",
            409,
            body={"message": "hi"},
        ),
    ]
    uploaded = _upload(app, checks)
    if uploaded:
        progress("Evaluating a small synthetic dataset with the stub model...")
        checks.append(run_check("app", "evaluation", lambda: _evaluation(app, uploaded)))
        checks += _view_checks(app, uploaded)
    checks.append(_route(app, "GET /logout", "GET", "/logout", expect=303))
    return checks


def _route(app, check_id, method, path, expect, body=None, html=False) -> Check:
    def probe() -> Check:
        answer = app.call(method, path, body=body, html=html)
        if answer.status == expect:
            return Check("", "", OK, f"HTTP {answer.status}")
        return Check("", "", FAIL, f"HTTP {answer.status} (expected {expect}): {answer.error()}")

    return run_check("app", check_id, probe)


def _wrong_password(app: LocalApp) -> Check:
    """The sign-in form answers and refuses a wrong password (the real one is never read)."""
    form = {"username": "doctor", "password": "not-the-password", "next": ""}
    answer = app.call("POST", "/login", form=form)
    if answer.status == 303 and answer.headers.get("location", "").startswith("login?e=1"):
        return Check("", "", OK, "a wrong password is refused")
    return Check("", "", FAIL, f"unexpected answer to a wrong password (HTTP {answer.status})")


def _session(app: LocalApp) -> Check:
    """A signed session cookie opens the API, as after a real sign-in."""
    expires = int(time.time()) + 600
    app.use_cookie(f"jfb_session={app.container.credentials.session(expires)}")
    if app.call("GET", "/api/system").status == 200:
        return Check("", "", OK, "a signed session opens the API")
    return Check(
        "",
        "",
        FAIL,
        "the session cookie was not accepted",
        "Delete secrets/session.key under JFB_HOME and start again.",
    )


def _datasets(app: LocalApp) -> Check:
    answer = app.call("GET", "/api/datasets")
    if answer.status != 200:
        return Check("", "", FAIL, f"HTTP {answer.status}: {answer.error()}")
    loaded = [entry["key"] for entry in answer.json()]
    missing = [key for key in BUILT_IN_DATASETS if key not in loaded]
    details = dict(loaded=loaded, missing=missing)
    if not missing:
        return Check(
            "", "", OK, f"HTTP 200, all {len(loaded)} built-in datasets loaded", details=details
        )
    return Check(
        "",
        "",
        WARN,
        f"HTTP 200, not loaded: {', '.join(missing)}",
        "Their download failed: see the network checks, or install the offline bundle.",
        details,
    )


def _upload(app: LocalApp, checks: list[Check]) -> str | None:
    """Upload and register the synthetic CSV; returns the new dataset key."""
    preview: dict = {}

    def upload() -> Check:
        answer = app.call("POST", "/api/upload", upload=("doctor-check.csv", _synthetic_csv()))
        if answer.status != 200:
            return Check("", "", FAIL, f"HTTP {answer.status}: {answer.error()}")
        preview.update(answer.json())
        return Check("", "", OK, f"HTTP 200, {preview['rows']} rows read")

    def register() -> Check:
        body = {
            "uid": preview["uid"],
            "date_col": "date",
            "target": "sales",
            "id_col": "store",
            "known": ["promo"],
            "cat": ["promo"],
            "calendar": True,
            "name": "Doctor check",
        }
        answer = app.call("POST", "/api/upload/register", body=body)
        if answer.status != 200:
            return Check("", "", FAIL, f"HTTP {answer.status}: {answer.error()}")
        preview["key"] = answer.json()["key"]
        return Check("", "", OK, "HTTP 200, dataset registered")

    checks.append(run_check("app", "POST /api/upload", upload))
    if "uid" not in preview:
        return None
    checks.append(run_check("app", "POST /api/upload/register", register))
    return preview.get("key")


def _evaluation(app: LocalApp, key: str) -> Check:
    deadline = time.monotonic() + EVALUATION_TIMEOUT
    while time.monotonic() < deadline:
        answer = app.call("POST", "/api/status", body={"dataset": key})
        if answer.status != 200:
            return Check("", "", FAIL, f"/api/status HTTP {answer.status}: {answer.error()}")
        variant = next(v for v in answer.json()["variants"] if v["key"] == DEFAULT_VARIANT)
        if variant["state"] == "done":
            return Check("", "", OK, "background evaluation finished")
        if variant["state"] == "error":
            return Check("", "", FAIL, f"background evaluation failed: {variant['error']}")
        time.sleep(0.5)
    return Check("", "", FAIL, "background evaluation did not finish in time")


def _view_checks(app: LocalApp, key: str) -> list[Check]:
    first = {"dataset": key, "series": 0}
    requests = [
        ("POST /api/status", "/api/status", {"dataset": key}),
        ("POST /api/run", "/api/run", {"dataset": key, "variant": DEFAULT_VARIANT}),
        ("POST /api/overview", "/api/overview", {"dataset": key}),
        ("POST /api/series", "/api/series", first),
        ("POST /api/ranking", "/api/ranking", first),
        ("POST /api/total", "/api/total", {"dataset": key}),
        ("POST /api/planner", "/api/planner", {"dataset": key}),
        ("POST /api/live", "/api/live", first),
        ("POST /api/replay", "/api/replay", {**first, "frames": 4}),
        ("POST /api/split", "/api/split", first),
        (
            "POST /api/whatif",
            "/api/whatif",
            {**first, "edits": [{"name": "promo", "mode": "set", "value": 1}]},
        ),  # noqa: E501
        ("POST /api/anomalies", "/api/anomalies", {**first, "windows": 4}),
    ]
    return [
        _route(app, check_id, "POST", path, 200, body=body) for check_id, path, body in requests
    ]


def _synthetic_csv() -> bytes:
    """Three made-up stores, 240 days, with a weekly cycle and a promo flag."""
    lines = ["date,store,sales,promo"]
    for store, level in (("A", 100), ("B", 160), ("C", 60)):
        for day in range(240):
            date = time.strftime("%Y-%m-%d", time.gmtime(1704067200 + day * 86400))
            promo = 1 if day % 14 < 3 else 0
            sales = level * (1.0 + 0.3 * (day % 7 == 5) + 0.2 * promo) + day * 0.1
            lines.append(f"{date},{store},{sales:.1f},{promo}")
    return ("\n".join(lines) + "\n").encode()


def _multipart(filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/csv\r\n\r\n"
    ).encode()
    return (
        head + content + f"\r\n--{boundary}--\r\n".encode(),
        f"multipart/form-data; boundary={boundary}",
    )


def _session_cookie(header: str) -> str:
    first = header.split(";", 1)[0].strip()
    return first if first.startswith("jfb_session=") else ""


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
