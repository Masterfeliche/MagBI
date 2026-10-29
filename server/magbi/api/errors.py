"""One JSON error shape for the whole API: ``{"error": {"code", "message", ...}}``."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from magbi.connectors.errors import ConnectorError, ErrorCode
from magbi.refresh.importer import ImportPipelineError
from magbi.refresh.orchestrator import RefreshConflict, RefreshLimit

# AUTH_FAILED is the *source* rejecting the saved credentials, not the caller's
# token, so it is a client error (400) and not a 401 that would trigger a re-login.
CONNECTOR_STATUS: dict[ErrorCode, int] = {
    ErrorCode.INVALID_CONFIG: 422,
    ErrorCode.UNSUPPORTED: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.AUTH_FAILED: 400,
    ErrorCode.UNREACHABLE: 502,
    ErrorCode.TIMEOUT: 504,
    ErrorCode.QUERY_FAILED: 502,
    ErrorCode.NOT_CONNECTED: 500,
}


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra


def error_body(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, **extra}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message, **exc.extra), status_code=exc.status
        )

    @app.exception_handler(ConnectorError)
    async def _connector(_: Request, exc: ConnectorError) -> JSONResponse:
        # ConnectorError messages are scrubbed of secrets where they are raised.
        status = CONNECTOR_STATUS.get(exc.code, 502)
        return JSONResponse(error_body(exc.code.value, exc.message), status_code=status)

    @app.exception_handler(ImportPipelineError)
    async def _pipeline(_: Request, exc: ImportPipelineError) -> JSONResponse:
        return JSONResponse(error_body("IMPORT_FAILED", str(exc)), status_code=422)

    @app.exception_handler(RefreshLimit)
    async def _limit(_: Request, exc: RefreshLimit) -> JSONResponse:
        return JSONResponse(
            error_body("REFRESH_LIMIT", str(exc), scope=exc.scope), status_code=429
        )

    @app.exception_handler(RefreshConflict)
    async def _conflict(_: Request, exc: RefreshConflict) -> JSONResponse:
        return JSONResponse(
            error_body("REFRESH_IN_PROGRESS", str(exc), refresh_id=str(exc.refresh_id)),
            status_code=409,
        )
