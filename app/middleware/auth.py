"""Authentication middleware — API Key hash verification, multi-key support, admin role isolation."""
from __future__ import annotations

import hashlib
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import config


def _sha256_hex(s: str) -> str:
    """Compute SHA-256 hex digest of a string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _verify_key(provided: str, allowed_keys: list[str], single_key: str) -> bool:
    """Verify API key against allowed list (hash comparison) or single key fallback.

    Comparison uses SHA-256 hash to avoid storing plaintext keys in memory comparisons.
    """
    if not provided:
        return False
    provided_hash = _sha256_hex(provided)

    # Multi-key mode: compare hashes
    for key in allowed_keys:
        if _sha256_hex(key) == provided_hash:
            return True

    # Single-key fallback (legacy)
    if single_key and _sha256_hex(single_key) == provided_hash:
        return True

    return False


def is_admin_key(provided: str) -> bool:
    """Check if the provided key is an admin key."""
    return _verify_key(provided, config.admin_keys, config.admin_key)


def is_api_key(provided: str) -> bool:
    """Check if the provided key is a regular API key (or admin key)."""
    return _verify_key(provided, config.api_keys, config.api_key) or is_admin_key(provided)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Require X-API-Key header for write operations; admin routes require admin key."""

    WRITE_METHODS = {"POST", "DELETE", "PUT", "PATCH"}
    # Routes that require admin-level access
    ADMIN_PREFIXES = ("/api/v1/admin",)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Admin routes: require admin key
        for prefix in self.ADMIN_PREFIXES:
            if request.url.path.startswith(prefix):
                admin_key = request.headers.get("X-API-Key")
                if not admin_key or not is_admin_key(admin_key):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "success": False,
                            "data": None,
                            "error": {
                                "code": "FORBIDDEN",
                                "message": "Admin key required for this operation",
                            },
                        },
                    )
                return await call_next(request)

        # Write operations: require any valid API key (admin key also works)
        if request.method in self.WRITE_METHODS:
            api_key = request.headers.get("X-API-Key")
            if not api_key or not is_api_key(api_key):
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