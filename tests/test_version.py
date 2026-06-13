"""
Tests for GET /api/version endpoint.

Covers:
- Status code 200
- Response JSON structure (version and service fields)
- Content-Type header
"""
from __future__ import annotations


class TestVersionEndpoint:
    """Test suite for GET /api/version endpoint."""

    def test_version_status_code_200(self, client):
        """AC-001: GET /api/version should return HTTP 200."""
        resp = client.get("/api/version")
        assert resp.status_code == 200

    def test_version_response_structure(self, client):
        """AC-002: Response body should be {'version': '1.0.0', 'service': 'shorturl'}."""
        resp = client.get("/api/version")
        data = resp.json()
        assert data["version"] == "1.0.0"
        assert data["service"] == "shorturl"

    def test_version_content_type_json(self, client):
        """AC-003: Content-Type should be application/json."""
        resp = client.get("/api/version")
        content_type = resp.headers.get("content-type", "")
        assert "application/json" in content_type

    def test_version_response_has_both_fields(self, client):
        """Ensure response contains both required fields."""
        resp = client.get("/api/version")
        data = resp.json()
        assert "version" in data
        assert "service" in data
        assert len(data) == 2  # Only these two fields

    def test_version_accept_header_json(self, client):
        """Test that Accept header is respected (requirement: when Accept is application/json)."""
        resp = client.get("/api/version", headers={"Accept": "application/json"})
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("application/json")
