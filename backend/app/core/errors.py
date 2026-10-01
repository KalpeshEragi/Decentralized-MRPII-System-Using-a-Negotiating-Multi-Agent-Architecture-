"""C5 error format: every non-2xx API response is {"error": {"code", "message", "details"}}."""

import logging
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    BUSINESS_RULE_VIOLATION = "BUSINESS_RULE_VIOLATION"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


STATUS = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INVALID_STATE_TRANSITION: 409,
    ErrorCode.BUSINESS_RULE_VIOLATION: 422,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}


class AppError(Exception):
    """Raised by services; the API layer turns it into the C5 body."""

    def __init__(self, code: ErrorCode, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []


def error_body(code: ErrorCode, message: str, details: list[dict] | None = None) -> dict:
    return {"error": {"code": code.value, "message": message, "details": details or []}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=STATUS[exc.code])

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "issue": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(
            error_body(ErrorCode.VALIDATION_ERROR, "request validation failed", details),
            status_code=STATUS[ErrorCode.VALIDATION_ERROR],
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INTERNAL_ERROR
        return JSONResponse(error_body(code, "not found" if code == ErrorCode.NOT_FOUND else "request failed"),
                            status_code=exc.status_code)

    @app.exception_handler(OperationalError)
    async def _database_down(_: Request, exc: OperationalError) -> JSONResponse:
        logger.error("database unavailable: %s", exc)
        return JSONResponse(
            error_body(ErrorCode.SERVICE_UNAVAILABLE, "the database is unavailable"),
            status_code=STATUS[ErrorCode.SERVICE_UNAVAILABLE],
        )

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # No stack traces, SQL or internals in the body (C5 section 1); details belong in the server log.
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(error_body(ErrorCode.INTERNAL_ERROR, "internal error"), status_code=500)
