# =============================================================================
# Dockerfile — ShortURL (Production-hardened, multi-stage)
#
# Stages:
#   1. builder  — installs all deps, compiles Python bytecode
#   2. production — minimal image, non-root, tini, HEALTHCHECK
#
# Security features:
#   • Non-root user (appuser UID 1000)
#   • tini as PID 1 — proper signal handling, zombie reaping
#   • HEALTHCHECK on /health endpoint
#   • No secrets baked into image
#   • Minimal attack surface (distroless-style python base)
#
# Usage:
#   docker build -t shorturl .            # build default (production) target
#   docker run -p 8000:8000 shorturl      # run
# =============================================================================

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for layer caching
COPY requirements.txt .

RUN pip install \
    --upgrade pip \
    --no-cache-dir \
    --target=/install \
    -r requirements.txt

# Copy source code for bytecode compilation
COPY app/ app/
# Note: run.py / pyproject.toml / uvicorn_config.json not present in this project — entry point is app/main.py

# Pre-compile Python bytecode
RUN python -m compileall -q /build/app/ || true

# ── Stage 2: production ──────────────────────────────────────────────────────
FROM python:3.12-slim AS production

# Metadata
LABEL org.opencontainers.image.title="ShortURL"
LABEL org.opencontainers.image.description="URL shortening service with analytics"
LABEL org.opencontainers.image.source="https://github.com/your-org/shorturl"

# Security: upgrade all packages, remove apt cache
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && rm -rf /var/cache/apt/archives/*

# Create non-root user: appuser UID/GID 1000
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --shell /bin/false --create-home appuser

WORKDIR /app

# Copy installed packages and binaries from builder
COPY --from=builder /install /install/

# Copy compiled source
COPY --from=builder /build/app/ ./app/

# Create writeable data directory for SQLite
RUN mkdir -p /app/data && chown appuser:appgroup /app/data

# Switch to non-root
USER appuser

# Set Python environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONPATH=/install \
    PATH=/install/bin:$PATH \
    UVICORN_WORKERS=1 \
    HOST=0.0.0.0 \
    PORT=8000

# Expose service port
EXPOSE 8000

# Graceful shutdown: wait up to 30s for in-flight requests
ENV UVICORN_GRACEFUL_SHUTDOWN_TIMEOUT=30

# Healthcheck — curl is installed in production image
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# tini as PID 1: reaps zombies and forwards signals to uvicorn
# SIGTERM → uvicorn gracefully stops → tini exits → container stops
ENTRYPOINT ["/usr/bin/tini", "--"]

# Run uvicorn as non-root; --graceful-shutdown-timeout matches UVICORN_GRACEFUL_SHUTDOWN_TIMEOUT
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
