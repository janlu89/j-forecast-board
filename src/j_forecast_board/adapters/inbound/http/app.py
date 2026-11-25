# SPDX-License-Identifier: Apache-2.0
"""The FastAPI app: routes translate HTTP to use-case calls and render the view models."""

from __future__ import annotations

import asyncio
import json
import os
import platform
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ....application.forecasts.split import SplitRequest
from ....application.forecasts.what_if import Edit, WhatIfRequest
from ....application.uploads import UploadSpec
from ....application.view_model import dataset_meta, to_plain
from ....application.views.planner import PlanRequest
from ....domain.forecast import MODEL_REPOS
from . import dtos, errors, static
from .security import BrowserGuard


def plain(value) -> JSONResponse:
    return JSONResponse(to_plain(value))


def create_app(services: Any, on_start: Callable[[], None] | None = None) -> FastAPI:
    """`services` is the composition root's container (see bootstrap.container.Container)."""

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if on_start is not None:
            on_start()
        yield

    app = FastAPI(
        title="J-Forecast Board", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    auth = services.authenticator
    app.middleware("http")(auth.middleware)
    guard = BrowserGuard(static.WEB / "index.html", trust_proxy=services.settings.trust_proxy)
    app.middleware("http")(guard.middleware)  # added last = runs first: refuse before signing in
    errors.install(app)
    _session_routes(app, auth)
    _catalog_routes(app, services)
    _analytics_routes(app, services)
    _forecast_routes(app, services)
    _upload_routes(app, services)
    _assistant_routes(app, services)
    static.install(app)
    return app


def _session_routes(app: FastAPI, auth) -> None:
    @app.get("/login")
    def login_page(request: Request):
        return auth.login_page(request)

    @app.post("/login")
    async def login_submit(request: Request):
        return await auth.login_submit(request)

    @app.get("/logout")
    def logout():
        return auth.logout()


def _catalog_routes(app: FastAPI, services) -> None:
    @app.get("/api/datasets")
    def datasets():
        return plain([dataset_meta(ds) for ds in services.catalog.list()])

    @app.get("/api/models")
    def models():
        model = services.model
        return [
            dict(id=repo, name=model.display_name(repo), cached=model.is_available(repo))
            for repo in MODEL_REPOS
        ]

    @app.get("/api/system")
    def system():
        info = dict(
            os=f"{platform.system()} {platform.release()} ({platform.version()})",
            cpu=platform.processor(),
            cores=os.cpu_count(),
            python=platform.python_version(),
            version=services.version,
            model_backend=services.settings.model,
            offline=services.settings.offline,
        )
        try:
            import torch

            info["torch"] = torch.__version__
        except ImportError:
            pass
        return info


def _analytics_routes(app: FastAPI, services) -> None:
    workbench = services.workbench

    def scope(r: dtos.DatasetRequest):
        return workbench.scope(r.dataset, r.horizon, r.context)

    @app.post("/api/status")
    def status(r: dtos.DatasetRequest):
        return plain(services.status.execute(scope(r)))

    @app.post("/api/run")
    def run(r: dtos.RunRequest):
        return plain(services.start_evaluation.execute(scope(r), r.variant))

    @app.post("/api/overview")
    def overview(r: dtos.DatasetRequest):
        return plain(services.overview.execute(scope(r)))

    @app.post("/api/series")
    def series(r: dtos.SeriesRequest):
        return plain(services.series.execute(scope(r), r.series, r.variant))

    @app.post("/api/ranking")
    def ranking(r: dtos.SeriesRequest):
        return plain(services.ranking.execute(scope(r), r.variant))

    @app.post("/api/total")
    def total(r: dtos.DatasetRequest):
        return plain(services.total.execute(scope(r)))

    @app.post("/api/planner")
    def planner(r: dtos.PlanBody):
        request = PlanRequest(r.series, r.scope, r.margin, r.holding, r.target)
        return plain(services.planner.execute(scope(r), r.variant, request))


def _forecast_routes(app: FastAPI, services) -> None:
    workbench = services.workbench

    def scope(r: dtos.DatasetRequest):
        return workbench.scope(r.dataset, r.horizon, r.context)

    @app.post("/api/live")
    def live(r: dtos.LiveRequest):
        return plain(services.live.execute(scope(r), r.series, r.variant, r.origin))

    @app.post("/api/replay")
    def replay(r: dtos.ReplayRequest):
        return plain(services.replay.execute(scope(r), r.series, r.variant, r.frames, r.span))

    @app.post("/api/split")
    def split(r: dtos.SplitRequestBody):
        request = SplitRequest(r.series, r.variant, r.start, r.split, r.end)
        return plain(services.split.execute(r.dataset, request))

    @app.post("/api/whatif")
    def what_if(r: dtos.WhatIfBody):
        edits = [Edit(e.name, e.mode, e.value, e.start, e.end) for e in r.edits]
        return plain(services.what_if.execute(scope(r), WhatIfRequest(r.series, r.variant, edits)))

    @app.post("/api/anomalies")
    def anomalies(r: dtos.AnomalyRequest):
        result = services.anomalies.execute(
            scope(r), r.series, r.variant, r.step, r.windows, r.level
        )
        return plain(result)


def _upload_routes(app: FastAPI, services) -> None:
    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):  # noqa: B008 - FastAPI's declaration style
        return plain(services.uploads.preview(await file.read(), file.filename))

    @app.post("/api/datasets/{key}/delete")
    def delete_dataset(key: str):
        services.uploads.forget(key)
        return dict(deleted=key)

    @app.post("/api/upload/register")
    def register(r: dtos.RegisterBody):
        spec = UploadSpec(**r.model_dump())
        return plain(services.uploads.register(spec))


def _assistant_routes(app: FastAPI, services) -> None:
    """The 'Ask about this page' panel and its setup."""
    setup, ask = services.assistant, services.ask

    @app.get("/api/assistant")
    def assistant():
        return setup.listing()

    @app.post("/api/assistant/agents/{agent_id}")
    def save_agent(agent_id: str, r: dtos.AgentBody):
        return setup.save(agent_id, r.model, r.base_url, r.api_key, r.clear_key)

    @app.post("/api/assistant/agents/{agent_id}/test")
    def test_agent(agent_id: str, r: dtos.AgentBody):
        return setup.test(agent_id, r.model, r.base_url, r.api_key)

    @app.post("/api/assistant/agents/{agent_id}/clear")
    def clear_agent(agent_id: str):
        return setup.clear(agent_id)

    @app.post("/api/assistant/agents/{agent_id}/revoke")
    def revoke_consent(agent_id: str):
        return setup.revoke(agent_id)

    @app.post("/api/assistant/activate")
    def activate(r: dtos.ActivateBody):
        return setup.activate(r.id, r.consent, r.private_data)

    @app.post("/api/assistant/deactivate")
    def deactivate():
        return setup.deactivate()

    @app.post("/api/assistant/context")
    def context_level(r: dtos.ContextBody):
        return setup.set_context_level(r.level)

    @app.post("/api/assistant/detect-local")
    def detect_local():
        from ....application.assistant.configuration import detect_local_servers

        return dict(servers=detect_local_servers(services.assistant_agents["local"]))

    @app.post("/api/chat")
    async def chat(r: dtos.ChatBody, request: Request):
        prepared = ask.prepare(r.message, r.history, r.context)  # errors become status codes
        host, port = request.scope.get("server") or ("127.0.0.1", 8000)
        local = "127.0.0.1" if host in ("0.0.0.0", "::", "", None) else host
        events = _stream(lambda emit: ask.answer(prepared, f"http://{local}:{port}", emit))
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(events, media_type="application/x-ndjson", headers=headers)

    @app.get("/internal/tools")
    def tool_list(request: Request):
        _check_tool_token(services, request)
        return dict(
            tools=[
                dict(name=t.name, description=t.description, inputSchema=t.schema)
                for t in ask_tools(services)
            ]
        )

    @app.post("/internal/tools/{name}")
    async def tool_call(name: str, request: Request):
        token = request.headers.get(TOOLS_TOKEN, "")
        arguments = await request.json()
        result = await asyncio.get_running_loop().run_in_executor(
            None, lambda: services.tool_gateway.call(token, name, arguments)
        )
        return dict(text=result.text)


TOOLS_TOKEN = "x-tools-token"


def ask_tools(services):
    from ....application.assistant.tools import SPECS

    return SPECS


def _check_tool_token(services, request: Request) -> None:
    from ....domain.errors import NotFound

    if not services.tool_gateway.is_open(request.headers.get(TOOLS_TOKEN, "")):
        raise NotFound("No open answer for this token.")


async def _stream(work):
    """Run a blocking answer in a worker thread and yield its events as NDJSON lines."""
    loop = asyncio.get_running_loop()
    events: asyncio.Queue = asyncio.Queue()

    def emit(kind: str, **fields) -> None:
        line = (json.dumps(dict(type=kind, **fields), default=str) + "\n").encode()
        loop.call_soon_threadsafe(events.put_nowait, line)

    def run() -> None:
        try:
            work(emit)
        finally:
            loop.call_soon_threadsafe(events.put_nowait, None)

    task = loop.run_in_executor(None, run)
    try:
        while (line := await events.get()) is not None:
            yield line
    finally:
        await task
