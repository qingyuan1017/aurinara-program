"""ASGI middleware for request correlation and access logging."""

import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.common.logging import request_id_context, request_method_context

logger = logging.getLogger(__name__)

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class RequestContextMiddleware:
    """Attach a safe request ID and emit one bounded access log."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        candidate = Headers(scope=scope).get("x-request-id")
        request_id = (
            candidate if candidate and REQUEST_ID_PATTERN.fullmatch(candidate) else uuid4().hex
        )
        scope.setdefault("state", {})["request_id"] = request_id
        started = perf_counter()
        status_code = 500
        token = request_id_context.set(request_id)
        method_token = request_method_context.set(str(scope.get("method", "GET")).upper())

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((perf_counter() - started) * 1000, 3)
            logger.info(
                "request completed",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_context.reset(token)
            request_method_context.reset(method_token)
