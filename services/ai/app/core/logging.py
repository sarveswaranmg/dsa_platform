"""Structured JSON logging with a request-id contextvar.

Duplicated per service by design (no cross-service imports). A log line is a
single JSON object; `request_id` is bound by the ASGI middleware from the
inbound `X-Request-ID` header so every service's lines for one front-end call
share an id.
"""

import json
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

REQUEST_ID_HEADER = "x-request-id"


def current_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str) -> None:
    _request_id.set(value)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "service": self._service,
            "msg": record.getMessage(),
            "request_id": current_request_id(),
        }
        # Any structured extras attached via logger.info(..., extra={...}).
        for key, value in getattr(record, "__dict__", {}).items():
            if key == "extra_fields" and isinstance(value, dict):
                payload.update(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(service: str, level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Route uvicorn's own loggers through the same JSON handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers[:] = [handler]
        logging.getLogger(name).propagate = False


# ASGI messages are heterogeneous by spec; Any keeps the header plumbing clean.
Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class RequestIdMiddleware:
    """Binds X-Request-ID (or mints one) for the duration of the request and
    echoes it on the response."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        raw = headers.get(REQUEST_ID_HEADER.encode())
        request_id = raw.decode() if raw else str(uuid.uuid4())
        token = _request_id.set(request_id)

        async def send_with_header(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers") or [])
                response_headers.append(
                    (REQUEST_ID_HEADER.encode(), request_id.encode())
                )
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self._app(scope, receive, send_with_header)
        finally:
            _request_id.reset(token)
