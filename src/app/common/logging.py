"""Structured logging with request correlation."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
request_method_context: ContextVar[str | None] = ContextVar("request_method", default=None)
request_path_context: ContextVar[str | None] = ContextVar("request_path", default=None)


class JsonFormatter(logging.Formatter):
    """Render bounded standard-library log records as JSON."""

    _reserved = frozenset(logging.makeLogRecord({}).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        embedded_metric = getattr(record, "embedded_metric", None)
        if isinstance(embedded_metric, dict):
            return json.dumps(
                embedded_metric,
                default=str,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_context.get()
        if request_id is not None:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key not in self._reserved and key not in {"message", "asctime"}:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str) -> None:
    """Configure process logging once at application composition."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
