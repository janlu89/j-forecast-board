# SPDX-License-Identifier: Apache-2.0
"""The FastAPI app: routes translate HTTP to use-case calls and render the view models."""

from __future__ import annotations

import os
import platform
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse

from ....application.forecasts.split import SplitRequest
from ....application.forecasts.what_if import Edit, WhatIfRequest
from ....application.uploads import UploadSpec
from ....application.view_model import dataset_meta, to_plain
from ....application.views.planner import PlanRequest
from ....domain.forecast import MODEL_REPOS
from . import dtos, errors, static


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

    @app.post("/api/upload/register")
    def register(r: dtos.RegisterBody):
        spec = UploadSpec(**r.model_dump())
        return plain(services.uploads.register(spec))


def _assistant_routes(app: FastAPI, services) -> None:
    """The chat panel and its agent settings (legacy modules, replaced in Phase 3)."""
    from fastapi.responses import StreamingResponse

    from .... import agents, chat

    @app.post("/api/chat")
    async def ask(r: dtos.ChatBody, request: Request):
        port = (request.scope.get("server") or ("127.0.0.1", 8000))[1]
        events = chat.stream(
            r.message, r.history, r.context, port, services.authenticator.internal_token
        )
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(events, media_type="application/x-ndjson", headers=headers)

    @app.get("/api/agents")
    def agent_list():
        return agents.listing()

    @app.post("/api/agents")
    def agent_save(r: dtos.AgentBody):
        key = "" if r.clear_key else (r.api_key or None)
        return agents.update(
            r.id, dict(model=r.model, base_url=r.base_url, api_key=key), r.activate
        )

    @app.post("/api/agents/test")
    def agent_test(r: dtos.AgentBody):
        return agents.test(r.id, dict(model=r.model, base_url=r.base_url, api_key=r.api_key))
