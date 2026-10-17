"""HTTP error format: RFC 9457 Problem Details with our fixed codes (backend_api.md §4, API-1, API-5)."""

import logging
import uuid
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
    FORBIDDEN = "FORBIDDEN"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


STATUS = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INVALID_STATE_TRANSITION: 409,
    ErrorCode.BUSINESS_RULE_VIOLATION: 422,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}


class AppError(Exception):
    """Raised by services; the API layer turns it into a Problem Details body."""

    def __init__(self, code: ErrorCode, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or []


TITLES = {
    ErrorCode.VALIDATION_ERROR: "Validation error",
    ErrorCode.NOT_FOUND: "Not found",
    ErrorCode.CONFLICT: "Conflict",
    ErrorCode.INVALID_STATE_TRANSITION: "Invalid state transition",
    ErrorCode.BUSINESS_RULE_VIOLATION: "Business rule violation",
    ErrorCode.FORBIDDEN: "Forbidden",
    ErrorCode.SERVICE_UNAVAILABLE: "Service unavailable",
    ErrorCode.INTERNAL_ERROR: "Internal error",
}
PROBLEM_JSON = "application/problem+json"
CORRELATION_HEADER = "X-Correlation-Id"


def error_body(code: ErrorCode, message: str, details: list[dict] | None = None, *, status: int | None = None,
               instance: str | None = None, correlation_id: str | None = None) -> dict:
    """RFC 9457 Problem Details (API-1): the standard members plus our `code`, `errors` and `correlation_id`.
    `type` is a URN per code (API-5)."""
    return {
        "type": f"urn:mrpii:problem:{code.value.lower().replace('_', '-')}",
        "title": TITLES[code],
        "status": status or STATUS[code],
        "detail": message,
        "instance": instance,
        "code": code.value,
        "errors": details or [],
        "correlation_id": correlation_id,
    }


def _problem(request: Request, code: ErrorCode, message: str, details: list[dict] | None = None,
             status: int | None = None) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", None)
    body = error_body(code, message, details, status=status, instance=request.url.path, correlation_id=correlation_id)
    headers = {CORRELATION_HEADER: correlation_id} if correlation_id else None
    return JSONResponse(body, status_code=body["status"], media_type=PROBLEM_JSON, headers=headers)


def install_correlation_id(app: FastAPI) -> None:
    """Every response carries `X-Correlation-Id`: taken from the request if given, otherwise new (backend_api.md §3)."""

    @app.middleware("http")
    async def _correlation(request: Request, call_next):
        request.state.correlation_id = request.headers.get(CORRELATION_HEADER) or str(uuid.uuid4())
        response = await call_next(request)
        response.headers[CORRELATION_HEADER] = request.state.correlation_id
        return response


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return _problem(request, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "issue": e["msg"]} for e in exc.errors()
        ]
        return _problem(request, ErrorCode.VALIDATION_ERROR, "request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INTERNAL_ERROR
        return _problem(request, code, "not found" if code == ErrorCode.NOT_FOUND else "request failed",
                        status=exc.status_code)

    @app.exception_handler(OperationalError)
    async def _database_down(request: Request, exc: OperationalError) -> JSONResponse:
        logger.error("database unavailable: %s", exc)
        return _problem(request, ErrorCode.SERVICE_UNAVAILABLE, "the database is unavailable")

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # No stack traces, SQL or internals in the body; details belong in the server log.
        logger.exception("unhandled error", exc_info=exc)
        return _problem(request, ErrorCode.INTERNAL_ERROR, "internal error")
