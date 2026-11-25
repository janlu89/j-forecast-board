# SPDX-License-Identifier: Apache-2.0
"""The one place where errors become HTTP status codes. The body is always {"error": message}."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ....domain import errors

log = logging.getLogger("j_forecast_board")

STATUS = {
    errors.InvalidRequest: 400,
    errors.PolicyViolation: 403,
    errors.NotFound: 404,
    errors.NotReady: 409,
    errors.NotConfigured: 409,
    errors.UpstreamError: 502,
    errors.ModelUnavailable: 503,
}
UNEXPECTED = "Something went wrong on the server. Details are in the app's console."


def install(app: FastAPI) -> None:
    @app.exception_handler(errors.DomainError)
    async def domain_error(_: Request, error: errors.DomainError):
        status = next((code for kind, code in STATUS.items() if isinstance(error, kind)), 400)
        return JSONResponse({"error": str(error)}, status_code=status)

    @app.exception_handler(ValueError)
    async def bad_value(_: Request, error: ValueError):
        # Values the request carried that a lower layer rejected (e.g. an invalid setting).
        return JSONResponse({"error": str(error)}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception):
        log.exception("Unexpected error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": UNEXPECTED}, status_code=500)
