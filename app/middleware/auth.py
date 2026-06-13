"""API Key authentication middleware — write operations require auth, reads are open."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import config


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Require X-API-Key header for POST/DELETE/PUT/PATCH requests."""

    WRITE_METHODS = {"POST", "DELETE", "PUT", "PATCH"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in self.WRITE_METHODS:
            api_key = request.headers.get("X-API-Key")
            if not api_key or api_key != config.api_key:
                return JSONResponse(
                    status_code=401,
                    content={
                        "success": False,
                        "data": None,
                        "error": {
                            "code": "UNAUTHORIZED",
                            "message": "Valid X-API-Key header required",
                        },
                    },
                )
        return await call_next(request)
