"""
Pytest fixtures for ShortURL tests.
Set test database BEFORE importing app modules.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# MUST be set before any app imports
os.environ["DATABASE_URL"] = "sqlite:///./test_shorturl.db"
os.environ["PROMETHEUS_ENABLED"] = "false"
# P0-2 FIX: Don't set RATE_LIMIT_PER_MINUTE globally - let tests control it
# Tests that need rate limiting disabled can set it in their own fixtures
# os.environ["RATE_LIMIT_PER_MINUTE"] = "999999"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="function")
def db_engine():
    """Create a test database engine with proper isolation.
    
    P0-1 FIX: Use a temporary database file for each test function to ensure
    complete isolation between tests, especially in coverage mode.
    """
    from app.models.link import Base
    
    # Create a temporary database file for each test
    # This ensures complete isolation between tests
    temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_db.close()
    db_path = temp_db.name
    
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    yield engine
    
    # Cleanup: drop tables and dispose engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    
    # Remove temporary database file
    try:
        Path(db_path).unlink()
    except Exception:
        pass  # Best effort cleanup


@pytest.fixture(scope="function")
def db_session(db_engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = Session()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def client(db_engine):
    """Create a test client with isolated test database.
    
    P0-1 FIX: Ensures tables are created in the isolated database engine.
    """
    from app.models.link import Base
    # Ensure tables exist in the isolated database
    Base.metadata.create_all(bind=db_engine)

    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    # Patch get_db at the correct location: links.py imports SessionLocal locally
    import app.routes.links as links_module

    _original_get_db = links_module.get_db

    def _test_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    links_module.get_db = _test_get_db

    # Also patch the module-level SessionLocal reference for any direct imports
    import app.database as db_module
    db_module.SessionLocal = TestSession
    db_module.engine = db_engine

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    # Restore
    links_module.get_db = _original_get_db
    # Don't drop tables here - db_engine fixture handles cleanup


@pytest.fixture
def sample_link(client):
    """Create a sample link and return its alias."""
    resp = client.post("/api/v1/links", json={"url": "https://example.com"})
    return resp.json()["data"]


# P0-2 FIX: Dynamic rate limit control for tests
@pytest.fixture(autouse=True)
def rate_limit_for_testing():
    """Control rate limiting based on test context.
    
    - For rate limit tests: Use realistic limit (10 req/min)
    - For other tests: Disable rate limiting (999999 req/min)
    
    This allows rate limit tests to verify actual behavior while keeping
    other tests fast and reliable.
    """
    import os
    
    # Check if we're in a rate limit test
    # We look at PYTEST_CURRENT_TEST which contains the test name
    current_test = os.environ.get("PYTEST_CURRENT_TEST", "")
    
    if "test_rate_limit" in current_test or "TestRateLimitBypass" in current_test:
        # Use realistic rate limit for rate limit tests
        os.environ["RATE_LIMIT_PER_MINUTE"] = "10"
        # Force reload of rate limit store
        import app.middleware.rate_limit as rate_limit_module
        rate_limit_module._rate_store = rate_limit_module.RateLimitStore(limit=10)
        yield
        # Reset after test
        os.environ["RATE_LIMIT_PER_MINUTE"] = "999999"
        rate_limit_module._rate_store = rate_limit_module.RateLimitStore(limit=999999)
    else:
        # Disable rate limiting for all other tests
        os.environ["RATE_LIMIT_PER_MINUTE"] = "999999"
        import app.middleware.rate_limit as rate_limit_module
        rate_limit_module._rate_store = rate_limit_module.RateLimitStore(limit=999999)
        yield