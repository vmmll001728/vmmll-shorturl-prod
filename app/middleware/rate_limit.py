"""Rate limiting middleware using in-memory token bucket."""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable, Dict, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import config


class RateLimitStore:
    """Simple in-memory rate limiter per IP."""

    def __init__(self, limit: int, window: int = 60):
        self.limit = limit
        self.window = window
        self._requests: Dict[str, list] = defaultdict(list)

    def is_allowed(self, key: str) -> Tuple[bool, int]:
        now = time.time()
        timestamps = self._requests[key]
        # Remove timestamps outside the window
        self._requests[key] = [t for t in timestamps if now - t < self.window]
        remaining = self.limit - len(self._requests[key])
        if remaining <= 0:
            return False, 0
        self._requests[key].append(now)
        return True, remaining - 1


_rate_store = RateLimitStore(limit=config.rate_limit_per_minute)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce per-IP rate limits."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for health and metrics endpoints
        if request.url.path in ("/health", "/metrics"):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        allowed, remaining = _rate_store.is_allowed(ip)
        if not allowed:
            return Response(
                content='{"success":false,"error":{"code":"RATE_LIMITED","message":"Too many requests"}}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "60", "X-RateLimit-Remaining": "0"},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response