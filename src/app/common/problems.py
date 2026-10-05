"""RFC 9457 problem details and FastAPI exception translation."""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ProblemDetails(BaseModel):
    """Public RFC 9457 problem representation."""

    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str
    issues: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ProblemException(Exception):
    """Typed application exception translated at the HTTP boundary."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        title: str,
        detail: str,
        problem_type: str | None = None,
        headers: dict[str, str] | None = None,
        issues: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.title = title
        self.detail = detail
        self.problem_type = problem_type or (
            f"https://aurinara.example/problems/{code.replace('_', '-')}"
        )
        self.headers = headers or {}
        self.issues = issues or []


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def _response(problem: ProblemDetails, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
        headers=headers,
    )


async def validation_exception_handler(
    request: Request, exception: RequestValidationError
) -> JSONResponse:
    """Translate transport validation failures without exposing Python internals."""

    errors = [
        {
            "location": [str(item) for item in error["loc"]],
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exception.errors()
    ]
    return _response(
        ProblemDetails(
            type="https://aurinara.example/problems/request-validation",
            title="Request validation failed",
            status=422,
            detail="The request does not satisfy the transport contract.",
            instance=request.url.path,
            code="request_validation_failed",
            request_id=_request_id(request),
            errors=errors,
        )
    )


async def problem_exception_handler(request: Request, exception: ProblemException) -> JSONResponse:
    """Translate an application error without parsing its message."""

    return _response(
        ProblemDetails(
            type=exception.problem_type,
            title=exception.title,
            status=exception.status_code,
            detail=exception.detail,
            instance=request.url.path,
            code=exception.code,
            request_id=_request_id(request),
            issues=exception.issues,
        ),
        exception.headers,
    )


async def http_exception_handler(request: Request, exception: HTTPException) -> JSONResponse:
    """Translate framework HTTP errors into the common problem shape."""

    title = "Request failed"
    detail = str(exception.detail)
    code = "http_error"
    if exception.status_code == 404:
        title = "Resource not found"
        code = "resource_not_found"
    return _response(
        ProblemDetails(
            type=f"https://aurinara.example/problems/{code.replace('_', '-')}",
            title=title,
            status=exception.status_code,
            detail=detail,
            instance=request.url.path,
            code=code,
            request_id=_request_id(request),
        )
    )


async def unexpected_exception_handler(request: Request, exception: Exception) -> JSONResponse:
    """Return a stable safe response and log the exception with correlation."""

    logger.exception("unhandled request exception", extra={"path": request.url.path})
    return _response(
        ProblemDetails(
            type="https://aurinara.example/problems/internal-error",
            title="Internal server error",
            status=500,
            detail="The server could not complete the request.",
            instance=request.url.path,
            code="internal_error",
            request_id=_request_id(request),
        )
    )


async def _dispatch_validation_exception(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, RequestValidationError):
        raise TypeError("expected RequestValidationError")
    return await validation_exception_handler(request, exception)


async def _dispatch_problem_exception(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, ProblemException):
        raise TypeError("expected ProblemException")
    return await problem_exception_handler(request, exception)


async def _dispatch_http_exception(request: Request, exception: Exception) -> JSONResponse:
    if not isinstance(exception, HTTPException):
        raise TypeError("expected HTTPException")
    return await http_exception_handler(request, exception)


def install_exception_handlers(app: FastAPI) -> None:
    """Install all public exception translators."""

    app.add_exception_handler(RequestValidationError, _dispatch_validation_exception)
    app.add_exception_handler(ProblemException, _dispatch_problem_exception)
    app.add_exception_handler(HTTPException, _dispatch_http_exception)
    app.add_exception_handler(Exception, unexpected_exception_handler)
