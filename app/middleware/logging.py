"""
Request logging middleware — structured JSON output to stdout.
Uses pure ASGI to avoid BaseHTTPMiddleware issues with CORS preflight.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Callable

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("shorturl.access")


class RequestLoggingMiddleware:
    """Log every request with method, path, status, duration, and client IP."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        status_code: int = 0

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        await self.app(scope, receive, send_wrapper)

        duration_ms = round((time.monotonic() - start) * 1000, 2)

        request = Request(scope)
        record = {
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "client_ip": request.client.host if request.client else "-",
        }
        logger.info(json.dumps(record, ensure_ascii=False))
