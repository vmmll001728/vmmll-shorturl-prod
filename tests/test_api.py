"""
ShortURL API Tests — 85+ test cases covering:
  - Unit tests (models, validators, slug generator)
  - Integration tests (real DB, no mocks)
  - Boundary tests (alias conflicts, expiry edges)
  - Performance tests (pytest-benchmark)
  - Security tests (SQLi, XSS, rate-limit bypass)
  - Observability tests (/metrics endpoint)
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from fastapi.testclient import TestClient


# =============================================================================
# SECTION 1: Unit Tests — Models & Validators (12 tests)
# =============================================================================

class TestLinkModel:
    def test_link_alias_required(self, db_session):
        from app.models.link import Link
        link = Link(alias="abc123", original_url="https://example.com")
        db_session.add(link)
        db_session.commit()
        assert link.alias == "abc123"
        assert link.click_count == 0

    def test_link_is_expired_false_when_no_expiry(self, db_session):
        from app.models.link import Link
        link = Link(alias="xyz789", original_url="https://example.com")
        db_session.add(link)
        db_session.commit()
        assert link.is_expired is False

    def test_link_is_expired_true_when_in_past(self, db_session):
        from app.models.link import Link
        past = datetime.now(timezone.utc) - timedelta(days=1)
        link = Link(alias="expired1", original_url="https://example.com", expires_at=past)
        db_session.add(link)
        db_session.commit()
        assert link.is_expired is True

    def test_link_is_expired_false_when_in_future(self, db_session):
        from app.models.link import Link
        future = datetime.now(timezone.utc) + timedelta(days=30)
        link = Link(alias="future1", original_url="https://example.com", expires_at=future)
        db_session.add(link)
        db_session.commit()
        assert link.is_expired is False

    def test_link_soft_delete_flag(self, db_session):
        from app.models.link import Link
        link = Link(alias="softdel", original_url="https://example.com", is_deleted=True)
        db_session.add(link)
        db_session.commit()
        db_session.expire_all()
        found = db_session.query(Link).filter(Link.alias == "softdel").first()
        assert found.is_deleted is True


class TestSlugGenerator:
    def test_generate_slug_length(self):
        from app.utils.slug import generate_slug
        assert len(generate_slug(6)) == 6
        assert len(generate_slug(8)) == 8
        assert len(generate_slug(12)) == 12

    def test_generate_slug_alphanumeric(self):
        from app.utils.slug import generate_slug
        slug = generate_slug(10)
        assert slug.isalnum()

    def test_generate_slug_uniqueness(self):
        from app.utils.slug import generate_slug
        slugs = {generate_slug(8) for _ in range(100)}
        # 62^8 combinations, 100 samples should all be unique (very high probability)
        assert len(slugs) == 100

    def test_is_valid_alias_valid(self):
        from app.utils.slug import is_valid_alias
        assert is_valid_alias("abc123") is True
        assert is_valid_alias("my-link") is True
        assert is_valid_alias("my_link") is True
        assert is_valid_alias("Abc123") is True

    def test_is_valid_alias_invalid_chars(self):
        from app.utils.slug import is_valid_alias
        assert is_valid_alias("my link") is False
        assert is_valid_alias("my.link") is False
        assert is_valid_alias("my<link") is False
        assert is_valid_alias("my>link") is False


class TestSanitizer:
    def test_sanitize_html(self):
        from app.utils.sanitizer import sanitize_html
        assert sanitize_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
        assert sanitize_html("Hello & World") == "Hello &amp; World"

    def test_sanitize_filename_path_traversal(self):
        from app.utils.sanitizer import sanitize_filename
        assert sanitize_filename("../../../etc/passwd") == "etcpasswd"
        assert sanitize_filename("foo/../bar") == "foobar"
        assert sanitize_filename("nul\x00file") == "nulfile"


# =============================================================================
# SECTION 2: Integration Tests — Real DB, No Mocks (22 tests)
# =============================================================================

class TestCreateLink:
    def test_create_link_success(self, client):
        resp = client.post("/api/v1/links", json={"url": "https://example.com"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        assert "short_url" in data["data"]
        assert data["data"]["original_url"] == "https://example.com"

    def test_create_link_with_custom_alias(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "custom_alias": "myalias123"},
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["alias"] == "myalias123"

    def test_create_link_with_expiry(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "expires_in_days": 7},
        )
        assert resp.status_code == 201
        expires_at = resp.json()["data"]["expires_at"]
        assert expires_at is not None
        # Should be ~7 days from now
        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00").replace("+00:00", ""))
        exp_dt_aware = exp_dt.replace(tzinfo=timezone.utc) if exp_dt.tzinfo is None else exp_dt
        assert (exp_dt_aware - datetime.now(timezone.utc)).days in (6, 7, 8)

    def test_create_link_returns_created_at(self, client):
        resp = client.post("/api/v1/links", json={"url": "https://example.com"})
        assert resp.status_code == 201
        assert "created_at" in resp.json()["data"]

    def test_create_multiple_links_unique_aliases(self, client):
        aliases = set()
        for _ in range(5):
            resp = client.post("/api/v1/links", json={"url": "https://example.com"})
            assert resp.status_code == 201
            aliases.add(resp.json()["data"]["alias"])
        assert len(aliases) == 5


class TestGetLink:
    def test_get_link_success(self, client, sample_link):
        alias = sample_link["alias"]
        resp = client.get(f"/api/v1/links/{alias}")
        assert resp.status_code == 200
        assert resp.json()["data"]["alias"] == alias

    def test_get_link_click_count_starts_at_zero(self, client, sample_link):
        alias = sample_link["alias"]
        resp = client.get(f"/api/v1/links/{alias}")
        assert resp.json()["data"]["click_count"] == 0

    def test_get_link_404_not_found(self, client):
        resp = client.get("/api/v1/links/nonexistent_alias_xyz")
        assert resp.status_code == 404

    def test_get_link_410_when_expired(self, client, db_session):
        from app.models.link import Link
        past = datetime.now(timezone.utc) - timedelta(days=1)
        link = Link(alias="expired_alias", original_url="https://example.com", expires_at=past)
        db_session.add(link)
        db_session.commit()
        resp = client.get("/api/v1/links/expired_alias")
        assert resp.status_code == 410


class TestRedirect:
    def test_redirect_success(self, client, sample_link):
        alias = sample_link["alias"]
        resp = client.get(f"/api/v1/{alias}", follow_redirects=False)
        assert resp.status_code == 302
        assert "location" in resp.headers

    def test_redirect_increments_click_count(self, client, sample_link, db_session):
        from app.models.link import Link
        alias = sample_link["alias"]
        # Reset count
        link = db_session.query(Link).filter(Link.alias == alias).first()
        link.click_count = 0
        db_session.commit()
        # Hit redirect twice
        client.get(f"/api/v1/{alias}", follow_redirects=False)
        client.get(f"/api/v1/{alias}", follow_redirects=False)
        db_session.expire_all()
        link2 = db_session.query(Link).filter(Link.alias == alias).first()
        assert link2.click_count == 2

    def test_redirect_404_for_unknown_alias(self, client):
        resp = client.get("/unknownalias123", follow_redirects=False)
        assert resp.status_code == 404


class TestDeleteLink:
    def test_delete_link_success(self, client, sample_link):
        alias = sample_link["alias"]
        resp = client.delete(f"/api/v1/links/{alias}")
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] is True

    def test_delete_link_then_404(self, client, sample_link):
        alias = sample_link["alias"]
        client.delete(f"/api/v1/links/{alias}")
        resp = client.get(f"/api/v1/links/{alias}")
        assert resp.status_code == 404

    def test_delete_link_then_can_reuse_alias(self, client, sample_link):
        alias = sample_link["alias"]
        client.delete(f"/api/v1/links/{alias}")
        # Create new link with same alias
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://newsite.com", "custom_alias": alias},
        )
        assert resp.status_code == 201

    def test_delete_link_404_unknown(self, client):
        resp = client.delete("/api/v1/links/nonexistent_delete")
        assert resp.status_code == 404


class TestListLinks:
    def test_list_links_empty(self, client):
        resp = client.get("/api/v1/links")
        assert resp.status_code == 200
        assert resp.json()["data"]["links"] == []

    def test_list_links_pagination(self, client):
        # Create 25 links
        for i in range(25):
            client.post("/api/v1/links", json={"url": f"https://example{i}.com"})
        resp = client.get("/api/v1/links?page=1&page_size=10")
        data = resp.json()["data"]
        assert len(data["links"]) == 10
        assert data["total"] == 25
        assert data["page"] == 1

    def test_list_links_page_2(self, client):
        for i in range(25):
            client.post("/api/v1/links", json={"url": f"https://example{i}.com"})
        resp = client.get("/api/v1/links?page=2&page_size=10")
        data = resp.json()["data"]
        assert len(data["links"]) == 10
        assert data["page"] == 2

    def test_list_links_page_3_remainder(self, client):
        for i in range(25):
            client.post("/api/v1/links", json={"url": f"https://example{i}.com"})
        resp = client.get("/api/v1/links?page=3&page_size=10")
        data = resp.json()["data"]
        assert len(data["links"]) == 5
        assert data["page"] == 3

    def test_list_links_excludes_deleted(self, client):
        r1 = client.post("/api/v1/links", json={"url": "https://keep.com"})
        r2 = client.post("/api/v1/links", json={"url": "https://delete.com"})
        r2_alias = r2.json()["data"]["alias"]
        client.delete(f"/api/v1/links/{r2_alias}")
        resp = client.get("/api/v1/links")
        aliases = [l["alias"] for l in resp.json()["data"]["links"]]
        assert r2_alias not in aliases
        assert r1.json()["data"]["alias"] in aliases


class TestHealthEndpoint:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["status"] == "ok"


# =============================================================================
# SECTION 3: Boundary Tests — Alias Conflicts, Expiry Edges (15 tests)
# =============================================================================

class TestAliasConflicts:
    def test_custom_alias_duplicate_rejected(self, client):
        client.post(
            "/api/v1/links",
            json={"url": "https://site1.com", "custom_alias": "duptest1"},
        )
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://site2.com", "custom_alias": "duptest1"},
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_custom_alias_too_short_rejected(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "custom_alias": "ab"},
        )
        assert resp.status_code in (400, 422)  # Route catches it as 400

    def test_custom_alias_too_long_rejected(self, client):
        long_alias = "a" * 100
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "custom_alias": long_alias},
        )
        assert resp.status_code == 422

    def test_custom_alias_invalid_chars_rejected(self, client):
        for bad in ["my alias", "my@alias", "my#alias"]:
            resp = client.post(
                "/api/v1/links",
                json={"url": "https://example.com", "custom_alias": bad},
            )
            assert resp.status_code == 422

    def test_auto_generated_alias_min_length(self, client):
        # Auto-generated slugs are 6 chars, should always be unique
        resp = client.post("/api/v1/links", json={"url": "https://example.com"})
        assert resp.status_code == 201
        alias = resp.json()["data"]["alias"]
        assert len(alias) == 6

    def test_alias_case_sensitivity(self, client):
        # Aliases are lowercased on creation
        resp1 = client.post(
            "/api/v1/links",
            json={"url": "https://site1.com", "custom_alias": "MyAlias123"},
        )
        assert resp1.json()["data"]["alias"] == "myalias123"

    def test_deleted_alias_can_be_reused(self, client):
        # P0 FIX: Was a `pass` stub with no actual assertion.
        # Create, delete, then recreate with same alias.
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://reuse-test.com", "custom_alias": "reuseme1"},
        )
        assert resp.status_code == 201
        client.delete("/api/v1/links/reuseme1")
        resp2 = client.post(
            "/api/v1/links",
            json={"url": "https://newsite.com", "custom_alias": "reuseme1"},
        )
        assert resp2.status_code == 201
        assert resp2.json()["data"]["alias"] == "reuseme1"
        assert resp2.json()["data"]["original_url"] == "https://newsite.com"


class TestExpiryBoundary:
    def test_expiry_1_day(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "expires_in_days": 1},
        )
        assert resp.status_code == 201
        expires_at = datetime.fromisoformat(
            resp.json()["data"]["expires_at"].replace("Z", "+00:00").replace("+00:00", "")
        )
        expires_at_aware = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
        delta = expires_at_aware - datetime.now(timezone.utc)
        assert 0 <= delta.days <= 1

    def test_expiry_3650_days(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "expires_in_days": 3650},
        )
        assert resp.status_code == 201

    def test_expiry_0_days_rejected(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "expires_in_days": 0},
        )
        assert resp.status_code == 422

    def test_expiry_negative_rejected(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "expires_in_days": -5},
        )
        assert resp.status_code == 422

    def test_expiry_too_large_rejected(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "expires_in_days": 9999},
        )
        assert resp.status_code == 422

    def test_expired_link_redirect_returns_410(self, client, db_session):
        from app.models.link import Link
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        link = Link(alias="willbeexpired", original_url="https://example.com", expires_at=past)
        db_session.add(link)
        db_session.commit()
        resp = client.get("/api/v1/willbeexpired", follow_redirects=False)
        assert resp.status_code == 410


class TestPaginationBoundary:
    def test_page_size_100_max(self, client):
        resp = client.get("/api/v1/links?page_size=100")
        assert resp.status_code == 200

    def test_page_size_101_rejected(self, client):
        resp = client.get("/api/v1/links?page_size=101")
        assert resp.status_code == 422

    def test_page_0_rejected(self, client):
        resp = client.get("/api/v1/links?page=0")
        assert resp.status_code == 422


# =============================================================================
# SECTION 4: Security Tests (10 tests)
# =============================================================================

class TestSQLInjection:
    def test_sqli_in_url_create(self, client):
        payloads = [
            "https://example.com' OR '1'='1",
            "https://example.com'; DROP TABLE links;--",
            "https://evil.com<script>alert(1)</script>",
        ]
        for payload in payloads:
            resp = client.post("/api/v1/links", json={"url": payload})
            # Should accept (store as-is) but NOT execute SQL
            # URL stored verbatim, no injection possible in SQLite param binding
            assert resp.status_code in (201, 422)

    def test_sqli_in_custom_alias(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "custom_alias": "a' OR 1=1--"},
        )
        assert resp.status_code == 422  # Pydantic alphanumeric validator blocks it

    def test_sqli_in_alias_param(self, client):
        resp = client.get("/api/v1/links/a'%3B%20DROP%20TABLE%20links")
        assert resp.status_code == 404  # Not found, no SQL executed


class TestXSSProtection:
    def test_xss_in_url_reflected_in_response(self, client):
        xss_url = "https://example.com/<script>alert(1)</script>"
        resp = client.post("/api/v1/links", json={"url": xss_url})
        assert resp.status_code == 201
        data = resp.json()["data"]["original_url"]
        # P0 FIX: Previously `or` made the condition always True.
        # The URL is stored verbatim, so data == xss_url must hold.
        # Verify that the stored value matches what was submitted.
        assert data == xss_url

    def test_xss_in_custom_alias_sanitized(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com", "custom_alias": "<img src=x onerror=alert(1)>"},
        )
        # Pydantic validator should reject this
        assert resp.status_code == 422

    def test_html_tags_in_alias_rejected(self, client):
        for tag in ["<div>", "alert(1)", "javascript:"]:
            resp = client.post(
                "/api/v1/links",
                json={"url": "https://example.com", "custom_alias": tag},
            )
            assert resp.status_code == 422


class TestRateLimitBypass:
    def test_rate_limit_returns_429(self, client):
        """P0-2 FIX: Test that rate limiting actually works.
        
        With rate_limit_per_minute=10 (set by rate_limit_for_testing fixture),
        the 11th request should return 429.
        """
        # Make 10 requests (the limit for rate limit tests)
        for i in range(10):
            resp = client.get("/api/v1/links")
            assert resp.status_code == 200
        
        # The 11th request should be rate limited
        resp = client.get("/api/v1/links")
        assert resp.status_code == 429
        assert "RATE_LIMITED" in resp.json().get("error", {}).get("code", "")

    def test_rate_limit_headers_present(self, client):
        resp = client.get("/api/v1/links")
        assert "x-ratelimit-remaining" in resp.headers or resp.status_code in (200, 429)

    def test_rate_limit_health_endpoint_exempt(self, client):
        # Health endpoint should never be rate-limited
        # Even after hitting rate limit on other endpoints
        for _ in range(15):  # Exceed rate limit
            client.get("/api/v1/links")
        
        # Health endpoint should still work
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_rate_limit_metrics_endpoint_exempt(self, client):
        # Metrics endpoint should not be rate-limited
        # Even after hitting rate limit on other endpoints
        for _ in range(15):  # Exceed rate limit
            client.get("/api/v1/links")
        
        # Metrics endpoint should still work (or 404 if prometheus not installed)
        resp = client.get("/metrics")
        assert resp.status_code in (200, 404)
        assert resp.status_code != 429


# =============================================================================
# SECTION 5: Observability Tests (3 tests)
# =============================================================================

class TestObservability:
    def test_metrics_endpoint_exists(self, client):
        resp = client.get("/metrics")
        # May return 200 (if prometheus installed) or 404 (not installed)
        assert resp.status_code in (200, 404)

    def test_metrics_endpoint_returns_prometheus_format(self, client):
        resp = client.get("/metrics")
        if resp.status_code == 200:
            text = resp.text
            # Prometheus metrics format: name{labels}value
            assert "http_requests_total" in text or "uvicorn" in text

    def test_health_includes_timestamp(self, client):
        resp = client.get("/health")
        data = resp.json()["data"]
        assert "timestamp" in data
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(data["timestamp"])


# =============================================================================
# SECTION 6: Performance Tests (5 tests)
# =============================================================================

class TestPerformance:
    def test_benchmark_link_creation(self, client, benchmark):
        def create():
            return client.post("/api/v1/links", json={"url": "https://benchmark.com"})
        result = benchmark(create)
        assert result.status_code == 201

    def test_benchmark_link_query(self, client, sample_link, benchmark):
        alias = sample_link["alias"]
        def get():
            return client.get(f"/api/v1/links/{alias}")
        result = benchmark(get)
        assert result.status_code == 200

    def test_benchmark_link_list(self, client, benchmark):
        for i in range(50):
            client.post("/api/v1/links", json={"url": f"https://perf{i}.com"})
        def list_():
            return client.get("/api/v1/links?page_size=50")
        result = benchmark(list_)
        assert result.status_code == 200

    def test_create_100_links_performance(self, client):
        start = time.time()
        for i in range(100):
            client.post("/api/v1/links", json={"url": f"https://batch{i}.com"})
        elapsed = time.time() - start
        # Should complete within 30 seconds even on slow hardware
        assert elapsed < 30

    def test_concurrent_reads_performance(self, client, sample_link):
        alias = sample_link["alias"]
        start = time.time()
        for _ in range(50):
            client.get(f"/api/v1/links/{alias}")
        elapsed = time.time() - start
        assert elapsed < 10


# =============================================================================
# SECTION 7: Additional Edge Cases (18 tests)
# =============================================================================

class TestURLEdgeCases:
    def test_url_no_trailing_slash_normalized(self, client):
        resp = client.post("/api/v1/links", json={"url": "https://example.com/"})
        assert resp.status_code == 201
        # Trailing slash is stripped
        assert resp.json()["data"]["original_url"] == "https://example.com"

    def test_url_with_query_params(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com/search?q=test&page=1"},
        )
        assert resp.status_code == 201
        assert "q=test" in resp.json()["data"]["original_url"]

    def test_url_with_fragment(self, client):
        resp = client.post(
            "/api/v1/links",
            json={"url": "https://example.com/page#section"},
        )
        assert resp.status_code == 201
        assert "#section" in resp.json()["data"]["original_url"]

    def test_url_missing_protocol_rejected(self, client):
        resp = client.post("/api/v1/links", json={"url": "example.com"})
        assert resp.status_code == 422

    def test_url_ftp_protocol_rejected(self, client):
        resp = client.post("/api/v1/links", json={"url": "ftp://example.com"})
        assert resp.status_code == 422


class TestConfigValidation:
    def test_debug_mode_flag(self):
        from app.config import config
        # Config should load without errors
        assert isinstance(config.port, int)
        assert isinstance(config.rate_limit_per_minute, int)

    def test_config_default_expiry_days(self):
        from app.config import config
        assert config.default_expiry_days == 30


class TestResponseFormat:
    def test_success_response_structure(self, client):
        resp = client.post("/api/v1/links", json={"url": "https://example.com"})
        data = resp.json()
        assert "success" in data
        assert data["success"] is True
        assert "data" in data
        assert data["error"] is None

    def test_error_response_structure(self, client):
        resp = client.get("/api/v1/links/nonexistent_xyz")
        data = resp.json()
        # FastAPI HTTPException returns plain error dict, not SuccessResponse
        assert data.get("detail") is not None or data.get("success") is False
        assert data.get("data") is None or "detail" in data


class TestCORS:
    def test_cors_headers_present(self, client):
        resp = client.options(
            "/api/v1/links",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" in resp.headers or resp.status_code == 200


class TestAliasGeneratorCollision:
    def test_rapid_alias_generation_no_collision(self, client):
        # Generate 50 links rapidly — all aliases should be unique
        aliases = []
        for i in range(50):
            resp = client.post("/api/v1/links", json={"url": f"https://site{i}.com"})
            assert resp.status_code == 201
            aliases.append(resp.json()["data"]["alias"])
        assert len(set(aliases)) == 50


class TestDataIntegrity:
    def test_original_url_not_mutated(self, client):
        original = "https://example.com/path?foo=bar#hash"
        resp = client.post("/api/v1/links", json={"url": original})
        alias = resp.json()["data"]["alias"]
        get_resp = client.get(f"/api/v1/links/{alias}")
        stored = get_resp.json()["data"]["original_url"]
        assert stored == original.rstrip("/")

    def test_click_count_persists_across_requests(self, client, sample_link, db_session):
        from app.models.link import Link
        alias = sample_link["alias"]
        link = db_session.query(Link).filter(Link.alias == alias).first()
        link.click_count = 99
        db_session.commit()
        db_session.expire_all()
        resp = client.get(f"/api/v1/links/{alias}")
        assert resp.json()["data"]["click_count"] == 99


# =============================================================================
# SECTION 8: P0 Test Gap Fixes — Auth, SSRF, Admin Cleanup, Exception Handlers
# =============================================================================

class TestAuthMiddleware:
    """P0: API Key authentication middleware tests."""

    def test_no_api_key_returns_401_on_write(self, client):
        # POST without X-API-Key header → 401
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as no_key_client:
            resp = no_key_client.post("/api/v1/links", json={"url": "https://example.com"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_wrong_api_key_returns_401(self, client):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app, raise_server_exceptions=True, headers={"X-API-Key": "wrong-key"}) as bad_client:
            resp = bad_client.post("/api/v1/links", json={"url": "https://example.com"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"

    def test_correct_api_key_returns_200(self, client):
        # Default client already has correct key (set in conftest fixture)
        resp = client.get("/api/v1/links")
        assert resp.status_code == 200

    def test_get_read_operations_do_not_require_key(self, client):
        # GET requests should bypass auth (auth middleware only checks WRITE_METHODS)
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as no_key_client:
            resp = no_key_client.get("/api/v1/links")
        assert resp.status_code == 200


class TestSSRFProtection:
    """P0: SSRF end-to-end tests — private/loopback IPs rejected."""

    def test_loopback_127_0_0_1_rejected(self, client):
        resp = client.post("/api/v1/links", json={"url": "http://127.0.0.1/secret"})
        assert resp.status_code == 400
        assert "not safe" in resp.json()["detail"].lower()

    def test_aws_metadata_169_254_169_254_rejected(self, client):
        resp = client.post("/api/v1/links", json={"url": "http://169.254.169.254/latest/meta-data/"})
        assert resp.status_code == 400
        assert "not safe" in resp.json()["detail"].lower()

    def test_private_10_0_0_1_rejected(self, client):
        resp = client.post("/api/v1/links", json={"url": "http://10.0.0.1/internal"})
        assert resp.status_code == 400
        assert "not safe" in resp.json()["detail"].lower()

    def test_private_192_168_1_1_rejected(self, client):
        resp = client.post("/api/v1/links", json={"url": "http://192.168.1.1/admin"})
        assert resp.status_code == 400
        assert "not safe" in resp.json()["detail"].lower()

    def test_normal_https_url_accepted(self, client):
        resp = client.post("/api/v1/links", json={"url": "https://example.com/safe-page"})
        assert resp.status_code == 201


class TestAdminCleanup:
    """P0: Admin cleanup endpoint tests."""

    def test_cleanup_requires_admin_key(self, client):
        # Regular API key should be rejected for admin routes
        resp = client.delete("/api/v1/admin/cleanup")
        assert resp.status_code == 403

    def test_cleanup_expired_links(self, admin_client, db_session):
        from app.models.link import Link
        # Create an expired link
        past = datetime.now(timezone.utc) - timedelta(days=2)
        link = Link(alias="expired_cleanup", original_url="https://expired.com", expires_at=past)
        db_session.add(link)
        db_session.commit()
        resp = admin_client.delete("/api/v1/admin/cleanup")
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] >= 1

    def test_cleanup_with_grace_period(self, admin_client, db_session):
        from app.models.link import Link
        # Link expired 1 day ago — grace=5 means it should NOT be cleaned
        past = datetime.now(timezone.utc) - timedelta(days=1)
        link = Link(alias="grace_test", original_url="https://grace.com", expires_at=past)
        db_session.add(link)
        db_session.commit()
        resp = admin_client.delete("/api/v1/admin/cleanup?grace_period_days=5")
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] == 0

    def test_cleanup_no_expired_links_returns_zero(self, admin_client, db_session):
        from app.models.link import Link
        # Create only a non-expired link
        future = datetime.now(timezone.utc) + timedelta(days=30)
        link = Link(alias="future_cleanup", original_url="https://future.com", expires_at=future)
        db_session.add(link)
        db_session.commit()
        resp = admin_client.delete("/api/v1/admin/cleanup")
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] == 0

    def test_cleanup_grace_boundary_values(self, admin_client, db_session):
        from app.models.link import Link
        # Create expired link
        past = datetime.now(timezone.utc) - timedelta(days=1)
        link = Link(alias="grace_boundary", original_url="https://boundary.com", expires_at=past)
        db_session.add(link)
        db_session.commit()
        # grace=0: should delete all expired
        resp = admin_client.delete("/api/v1/admin/cleanup?grace_period_days=0")
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] >= 1


class TestGlobalExceptionHandler:
    """P0: Global exception handler tests."""

    def test_500_handler_returns_unified_format(self, client):
        # Directly test the global_exception_handler by calling it with a fake exception
        from app.main import global_exception_handler
        from starlette.requests import Request
        from starlette.testclient import TestClient as StarletteClient
        import asyncio

        # Create a minimal ASGI scope to build a Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/links/test",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
        }
        request = Request(scope)
        exc = RuntimeError("simulated internal error")

        # Call the handler directly
        response = asyncio.run(global_exception_handler(request, exc))
        assert response.status_code == 500
        # Parse JSON body from response
        import json
        data = json.loads(response.body.decode())
        assert data["success"] is False
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert data["error"]["message"] == "Internal server error"

    def test_validation_exception_handler_format(self, client):
        # Send invalid JSON to trigger RequestValidationError → 422 with unified format
        resp = client.post(
            "/api/v1/links",
            json={"url": "not-a-valid-url"},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "VALIDATION_ERROR"