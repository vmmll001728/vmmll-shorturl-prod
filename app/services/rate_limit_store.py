"""Rate limiting store implementations - in-memory and Redis-backed.

This module provides rate limit storage backends:
- InMemoryRateLimitStore: Simple in-memory storage using sliding window
- RedisRateLimitStore: Distributed rate limiting using Redis sorted sets (ZSET)
- get_rate_limit_store: Factory function to auto-select backend based on config
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, Optional, Tuple

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore

from app.config import config


class InMemoryRateLimitStore:
    """Simple in-memory rate limiter per key using sliding window.

    This implementation is suitable for single-process deployments.
    For multi-process or distributed deployments, use RedisRateLimitStore.

    Args:
        limit: Maximum number of requests allowed in the window
        window: Window size in seconds (default: 60)

    Example:
        >>> store = InMemoryRateLimitStore(limit=100, window=60)
        >>> allowed, remaining = store.is_allowed("192.168.1.1")
    """

    def __init__(self, limit: int, window: int = 60):
        self.limit = limit
        self.window = window
        self._requests: Dict[str, list] = defaultdict(list)

    def is_allowed(self, key: str) -> Tuple[bool, int]:
        """Check if request is allowed using sliding window algorithm.

        Args:
            key: Identifier for the client (e.g., IP address)

        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
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

    def reset(self, key: str) -> None:
        """Reset rate limit for a specific key (useful for testing)."""
        self._requests.pop(key, None)


class RedisRateLimitStore:
    """Redis-backed rate limiter using sliding window algorithm.

    Uses Redis sorted sets (ZSET) to implement distributed sliding window rate limiting.
    Each request is stored with its timestamp as the score.

    This implementation is suitable for multi-process or distributed deployments
    where a shared rate limit state is required.

    Args:
        redis_url: Redis connection URL (e.g., redis://localhost:6379/0)
        limit: Maximum number of requests allowed in the window
        window: Window size in seconds (default: 60)

    Example:
        >>> store = RedisRateLimitStore("redis://localhost:6379/0", limit=100, window=60)
        >>> allowed, remaining = store.is_allowed("192.168.1.1")
    """

    def __init__(self, redis_url: str, limit: int, window: int = 60):
        if not REDIS_AVAILABLE:
            raise ImportError(
                "redis package is not installed. "
                "Install it with: pip install redis>=5.0.0"
            )

        self.limit = limit
        self.window = window

        # Create Redis connection pool
        self._redis_pool = redis.ConnectionPool.from_url(
            redis_url,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        self._redis_client = redis.Redis(connection_pool=self._redis_pool)

        # Test connection
        try:
            self._redis_client.ping()
        except redis.ConnectionError as e:
            raise ConnectionError(f"Cannot connect to Redis at {redis_url}: {e}")

    @property
    def redis(self) -> "redis.Redis":
        """Get the Redis client instance."""
        return self._redis_client

    def is_allowed(self, key: str) -> Tuple[bool, int]:
        """Check if request is allowed using Redis sorted set sliding window.

        Uses atomic pipeline to ensure consistency:
        1. Remove entries outside the window (ZREMRANGEBYSCORE)
        2. Count requests in current window (ZCARD)
        3. Add current request (ZADD)
        4. Set expiry for key cleanup (EXPIRE)

        Args:
            key: Identifier for the client (e.g., IP address)

        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        now = time.time()
        window_start = now - self.window
        key = f"ratelimit:{key}"  # Namespace the key

        # Use pipeline for atomic operations
        pipe = self._redis_client.pipeline()

        # Step 1: Remove entries outside the window
        pipe.zremrangebyscore(key, 0, window_start)

        # Step 2: Count requests in current window
        pipe.zcard(key)

        # Step 3: Add current request (use timestamp as member and score)
        # Use microseconds to avoid collisions
        member = f"{now}:{time.perf_counter()}"
        pipe.zadd(key, {member: now})

        # Step 4: Set expiry to clean up old keys (2x window for safety)
        pipe.expire(key, self.window * 2)

        results = pipe.execute()
        current_count = results[1]

        if current_count >= self.limit:
            # Remove the request we just added (not allowed)
            self._redis_client.zrem(key, member)
            return False, 0

        remaining = self.limit - current_count - 1  # -1 for current request
        return True, max(remaining, 0)

    def reset(self, key: str) -> None:
        """Reset rate limit for a specific key."""
        self._redis_client.delete(f"ratelimit:{key}")

    def close(self) -> None:
        """Close Redis connections."""
        self._redis_client.close()
        self._redis_pool.disconnect()


def get_rate_limit_store():
    """Factory function to initialize rate limit store based on configuration.

    Uses Redis if REDIS_URL is configured and Redis is available,
    otherwise falls back to in-memory store.

    Returns:
        An instance of InMemoryRateLimitStore or RedisRateLimitStore

    Example:
        >>> store = get_rate_limit_store()
        >>> allowed, remaining = store.is_allowed("192.168.1.1")
    """
    # Try Redis if configured
    if config.redis_url and REDIS_AVAILABLE:
        try:
            return RedisRateLimitStore(
                redis_url=config.redis_url,
                limit=config.rate_limit_per_minute,
                window=60,  # 60 seconds window
            )
        except (redis.ConnectionError, redis.TimeoutError) as e:
            print(f"Warning: Redis connection failed, falling back to in-memory: {e}")
        except Exception as e:
            print(f"Warning: Redis initialization error, falling back to in-memory: {e}")

    # Fallback to in-memory
    return InMemoryRateLimitStore(
        limit=config.rate_limit_per_minute,
        window=60,
    )
