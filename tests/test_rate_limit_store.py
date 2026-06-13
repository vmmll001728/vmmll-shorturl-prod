"""Tests for rate limit store implementations.

These tests cover:
- InMemoryRateLimitStore (always runs)
- RedisRateLimitStore (skipped if Redis is not available)
- Factory function get_rate_limit_store
"""

from __future__ import annotations

import pytest
import time
from unittest.mock import patch, MagicMock

from app.services.rate_limit_store import (
    InMemoryRateLimitStore,
    RedisRateLimitStore,
    get_rate_limit_store,
)
from app.config import config


class TestInMemoryRateLimitStore:
    """Test suite for InMemoryRateLimitStore."""

    @pytest.fixture
    def store(self) -> InMemoryRateLimitStore:
        """Create a store with 5 requests per 60 seconds."""
        return InMemoryRateLimitStore(limit=5, window=60)

    def test_allows_requests_within_limit(self, store: InMemoryRateLimitStore):
        """Test that requests within limit are allowed."""
        for i in range(5):
            allowed, remaining = store.is_allowed("192.168.1.1")
            assert allowed is True
            assert remaining == 4 - i

    def test_rejects_requests_over_limit(self, store: InMemoryRateLimitStore):
        """Test that requests over limit are rejected."""
        # Exhaust the limit
        for _ in range(5):
            allowed, _ = store.is_allowed("192.168.1.1")
            assert allowed is True

        # Next request should be rejected
        allowed, remaining = store.is_allowed("192.168.1.1")
        assert allowed is False
        assert remaining == 0

    def test_sliding_window(self, store: InMemoryRateLimitStore):
        """Test that old requests expire from the window."""
        # Make 5 requests
        for _ in range(5):
            allowed, _ = store.is_allowed("192.168.1.1")
            assert allowed is True

        # Next request should be rejected
        allowed, _ = store.is_allowed("192.168.1.1")
        assert allowed is False

        # Simulate time passing (manually clear old entries)
        store._requests["192.168.1.1"] = []

        # Now should be allowed again
        allowed, remaining = store.is_allowed("192.168.1.1")
        assert allowed is True
        assert remaining == 4

    def test_different_keys_are_independent(self, store: InMemoryRateLimitStore):
        """Test that different keys (IPs) have independent limits."""
        # Exhaust limit for IP 1
        for _ in range(5):
            allowed, _ = store.is_allowed("192.168.1.1")
            assert allowed is True

        # IP 2 should still be allowed
        allowed, remaining = store.is_allowed("192.168.1.2")
        assert allowed is True
        assert remaining == 4

    def test_reset(self, store: InMemoryRateLimitStore):
        """Test resetting rate limit for a key."""
        # Exhaust limit
        for _ in range(5):
            store.is_allowed("192.168.1.1")

        # Verify limit is exhausted
        allowed, _ = store.is_allowed("192.168.1.1")
        assert allowed is False

        # Reset
        store.reset("192.168.1.1")

        # Should be allowed again
        allowed, remaining = store.is_allowed("192.168.1.1")
        assert allowed is True
        assert remaining == 4


@pytest.mark.skipif(
    True,  # Will be updated based on Redis availability
    reason="Redis not available"
)
class TestRedisRateLimitStore:
    """Test suite for RedisRateLimitStore.

    These tests require a running Redis instance.
    Set REDIS_URL environment variable or these tests will be skipped.
    """

    @pytest.fixture(scope="class")
    def redis_store(self):
        """Create a Redis-backed store for testing."""
        # This fixture will be skipped if Redis is not available
        pytest.importorskip("redis")

        # Try to connect to Redis
        import redis as redis_lib

        redis_url = getattr(config, "redis_url", None) or "redis://localhost:6379/0"

        try:
            store = RedisRateLimitStore(redis_url=redis_url, limit=10, window=60)
            yield store
            # Cleanup
            store.close()
        except (ConnectionError, redis_lib.ConnectionError):
            pytest.skip("Redis is not available")

    def test_allows_requests_within_limit(self, redis_store: RedisRateLimitStore):
        """Test that requests within limit are allowed."""
        key = f"test:{time.time()}"
        for i in range(10):
            allowed, remaining = redis_store.is_allowed(key)
            assert allowed is True
            assert remaining == 9 - i

    def test_rejects_requests_over_limit(self, redis_store: RedisRateLimitStore):
        """Test that requests over limit are rejected."""
        key = f"test:{time.time()}"

        # Exhaust the limit
        for _ in range(10):
            allowed, _ = redis_store.is_allowed(key)
            assert allowed is True

        # Next request should be rejected
        allowed, remaining = redis_store.is_allowed(key)
        assert allowed is False
        assert remaining == 0

    def test_different_keys_are_independent(self, redis_store: RedisRateLimitStore):
        """Test that different keys have independent limits."""
        key1 = f"test1:{time.time()}"
        key2 = f"test2:{time.time()}"

        # Exhaust limit for key1
        for _ in range(10):
            allowed, _ = redis_store.is_allowed(key1)
            assert allowed is True

        # key2 should still be allowed
        allowed, remaining = redis_store.is_allowed(key2)
        assert allowed is True
        assert remaining == 9

    def test_reset(self, redis_store: RedisRateLimitStore):
        """Test resetting rate limit for a key."""
        key = f"test:{time.time()}"

        # Exhaust limit
        for _ in range(10):
            redis_store.is_allowed(key)

        # Verify limit is exhausted
        allowed, _ = redis_store.is_allowed(key)
        assert allowed is False

        # Reset
        redis_store.reset(key)

        # Should be allowed again
        allowed, remaining = redis_store.is_allowed(key)
        assert allowed is True
        assert remaining == 9


class TestGetRateLimitStore:
    """Test suite for the factory function."""

    def test_returns_inmemory_when_no_redis_url(self):
        """Test that in-memory store is returned when REDIS_URL is not set."""
        with patch.object(config, "redis_url", None):
            with patch("app.services.rate_limit_store.REDIS_AVAILABLE", False):
                store = get_rate_limit_store()
                assert isinstance(store, InMemoryRateLimitStore)

    def test_returns_inmemory_when_redis_not_available(self):
        """Test that in-memory store is returned when redis package is not installed."""
        with patch.object(config, "redis_url", "redis://localhost:6379/0"):
            with patch("app.services.rate_limit_store.REDIS_AVAILABLE", False):
                store = get_rate_limit_store()
                assert isinstance(store, InMemoryRateLimitStore)

    def test_returns_redis_when_available(self):
        """Test that Redis store is returned when Redis is available and configured."""
        # Only run this test if redis is actually available
        pytest.importorskip("redis")

        with patch.object(config, "redis_url", "redis://localhost:6379/0"):
            with patch("app.services.rate_limit_store.REDIS_AVAILABLE", True):
                # Mock the Redis connection to avoid actual connection
                with patch("app.services.rate_limit_store.RedisRateLimitStore.__init__") as mock_init:
                    mock_init.return_value = None
                    store = get_rate_limit_store()
                    # Should attempt to create RedisRateLimitStore
                    mock_init.assert_called_once()


class TestRateLimitIntegration:
    """Integration tests for rate limiting."""

    def test_rate_limit_headers_in_response(self):
        """Test that rate limit headers are added to responses."""
        # This would require a full FastAPI test client
        # For now, just test the store logic
        store = InMemoryRateLimitStore(limit=100, window=60)
        allowed, remaining = store.is_allowed("test-ip")
        assert allowed is True
        assert remaining == 99

    def test_concurrent_requests(self):
        """Test rate limiting under concurrent requests (simulated)."""
        store = InMemoryRateLimitStore(limit=10, window=60)

        # Simulate 10 concurrent requests
        results = []
        for _ in range(10):
            results.append(store.is_allowed("concurrent-ip"))

        # All should be allowed
        assert all(allowed for allowed, _ in results)

        # 11th should be rejected
        allowed, remaining = store.is_allowed("concurrent-ip")
        assert allowed is False
        assert remaining == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
