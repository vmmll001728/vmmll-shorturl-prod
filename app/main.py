"""
ShortURL – FastAPI Short Link Service with Prometheus metrics.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import logging

# Configure structured logging — JSON-friendly, container-friendly
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

from app.config import config
from app.database import init_db
from app.middleware.auth import APIKeyMiddleware
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.routes.links import router as links_router
from app.routes.version import router as version_router
from app.types.models import HealthCheck, SuccessResponse

# Prometheus instrumentator - imported lazily so the app works even if prometheus is absent
_prometheus_available = False
Instrumentator = None
try:
    from prometheus_fastapi_instrumentator import Instrumentator as _Instr
    Instrumentator = _Instr
    _prometheus_available = True
except ImportError:
    pass


# 不安全的 SECRET_KEY 默认值列表
_UNSAFE_SECRET_KEYS = frozenset({
    "dev-secret-change-in-prod",
    "change-me-in-production",
    "changeme",
})


def _check_secret_key():
    """应用启动前强制校验 SECRET_KEY，防止遗忘配置时以弱密钥运行。"""
    if not config.secret_key or config.secret_key in _UNSAFE_SECRET_KEYS:
        print(
            f"[CONFIG ERROR] SECRET_KEY 使用了不安全默认值！\n"
            f"  当前值: '{config.secret_key}'\n"
            f"  必须通过环境变量 SECRET_KEY 设置一个强随机值。\n"
            f"  示例: SECRET_KEY=$(python -c \"import secrets; print(secrets.token_hex(32))\")\n",
            file=sys.stderr,
        )
        sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_secret_key()
    init_db()
    yield


app = FastAPI(
    title="ShortURL",
    version=config.app_version,
    description="URL shortening service with analytics",
    lifespan=lifespan,
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(APIKeyMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

# Routes
app.include_router(links_router)
app.include_router(version_router)


@app.get("/health", response_model=SuccessResponse, tags=["health"])
def health() -> SuccessResponse:
    """Health check endpoint."""
    return SuccessResponse(
        data={
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            "version": config.app_version,
        }
    )


# Prometheus metrics - expose at /metrics
if Instrumentator is not None:
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=config.host, port=config.port, reload=config.debug)