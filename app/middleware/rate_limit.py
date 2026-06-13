"""Rate limiting middleware.

This middleware enforces per-IP rate limits using the rate limit store
from app.services.rate_limit_store.
"""

from __future__ import annotations

from typing import Callable, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.services.rate_limit_store import get_rate_limit_store

# Initialize rate limit store using the factory function
_rate_store = get_rate_limit_store()


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
