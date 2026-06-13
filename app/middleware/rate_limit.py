"""Rate limiting middleware with Redis and in-memory support."""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable, Dict, Optional, Tuple

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import config


class RateLimitStore:
    """Simple in-memory rate limiter per IP using sliding window."""

    def __init__(self, limit: int, window: int = 60):
        self.limit = limit
        self.window = window
        self._requests: Dict[str, list] = defaultdict(list)

    def is_allowed(self, key: str) -> Tuple[bool, int]:
        """Check if request is allowed using sliding window algorithm."""
        now = time.time()
        window_start = now - self.window
        
        # Get existing timestamps and filter out old ones
        timestamps = self._requests[key]
        valid_timestamps = [t for t in timestamps if t > window_start]
        
        if len(valid_timestamps) >= self.limit:
            return False, 0
        
        valid_timestamps.append(now)
        self._requests[key] = valid_timestamps
        remaining = self.limit - len(valid_timestamps)
        return True, remaining


class RedisRateLimitStore:
    """Redis-backed rate limiter using sliding window algorithm.
    
    Uses sorted sets to implement sliding window rate limiting.
    Each request is stored with its timestamp as score.
    """
    
    def __init__(self, redis_client: redis.Redis, limit: int, window: int = 60):
        self.redis = redis_client
        self.limit = limit
        self.window = window
    
    def is_allowed(self, key: str) -> Tuple[bool, int]:
        """Check if request is allowed using Redis sorted set sliding window."""
        now = time.time()
        window_start = now - self.window
        
        # Use pipeline for atomic operations
        pipe = self.redis.pipeline()
        
        # Remove entries outside the window
        pipe.zremrangebyscore(key, 0, window_start)
        
        # Count requests in current window
        pipe.zcard(key)
        
        # Add current request
        pipe.zadd(key, {str(now): now})
        
        # Set expiry to clean up old keys
        pipe.expire(key, self.window * 2)
        
        results = pipe.execute()
        current_count = results[1]
        
        if current_count >= self.limit:
            # Remove the request we just added (not allowed)
            self.redis.zrem(key, str(now))
            return False, 0
        
        remaining = self.limit - current_count - 1  # -1 for current request
        return True, max(remaining, 0)


def _get_rate_store():
    """Initialize rate limit store based on configuration.
    
    Uses Redis if REDIS_URL is configured, otherwise falls back to in-memory.
    """
    if config.redis_url:
        try:
            import redis
            
            redis_client = redis.from_url(
                config.redis_url,
                decode_responses=False,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Test connection
            redis_client.ping()
            return RedisRateLimitStore(
                redis_client=redis_client,
                limit=config.rate_limit_per_minute
            )
        except ImportError:
            print("Warning: redis package not installed, falling back to in-memory")
        except (redis.ConnectionError, redis.TimeoutError) as e:
            print(f"Warning: Redis connection failed, falling back to in-memory: {e}")
    
    # Fallback to in-memory
    return RateLimitStore(limit=config.rate_limit_per_minute)


_rate_store = _get_rate_store()


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