"""Unit and Integration Tests for Enterprise features.

Covers:
- Configuration (Pydantic settings)
- Caching Service (InMemoryCache)
- Middlewares (TraceAndLog, SecurityHeaders, RateLimiting)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from app.services.cache import InMemoryCache, get_cache
from app.utils.config import Settings, get_settings


# ---------------------------------------------------------------------------
# Caching Service Tests
# ---------------------------------------------------------------------------

def test_in_memory_cache_operations():
    cache = InMemoryCache()

    # Get non-existent key
    assert cache.get("key1") is None

    # Set and get key
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"

    # Delete key
    cache.delete("key1")
    assert cache.get("key1") is None


def test_in_memory_cache_ttl():
    cache = InMemoryCache()

    # Set key with 0.1s TTL
    cache.set("key_ttl", "value_ttl", ttl_seconds=0.1)
    assert cache.get("key_ttl") == "value_ttl"

    # Wait for TTL to expire
    time.sleep(0.15)
    assert cache.get("key_ttl") is None


def test_generate_key():
    from app.services.cache import BaseCache

    k1 = BaseCache.generate_key("prefix", "arg1", kwarg1="val1")
    k2 = BaseCache.generate_key("prefix", "arg1", kwarg1="val1")
    k3 = BaseCache.generate_key("prefix", "arg2", kwarg1="val1")

    assert k1 == k2
    assert k1 != k3


# ---------------------------------------------------------------------------
# Middleware Integration Tests
# ---------------------------------------------------------------------------

@pytest.fixture
def test_app():
    from fastapi.middleware.cors import CORSMiddleware
    from app.middleware import (
        TraceAndLogMiddleware,
        SecurityHeadersMiddleware,
        RateLimitMiddleware,
    )

    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(TraceAndLogMiddleware)

    @app.get("/test-endpoint")
    def endpoint():
        return {"status": "ok"}

    return app


def test_request_id_and_security_headers(test_app):
    get_cache().clear()
    client = TestClient(test_app)
    response = client.get("/test-endpoint")

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "Strict-Transport-Security" in response.headers
    assert "Content-Security-Policy" in response.headers


def test_rate_limiting_middleware(test_app):
    get_cache().clear()
    # Temporarily set rate limit to 2 per minute for testing
    test_settings = Settings(rate_limit_requests_per_minute=2)

    with patch("app.middleware.get_settings", return_value=test_settings):
        client = TestClient(test_app)

        # First request should pass
        r1 = client.get("/test-endpoint")
        assert r1.status_code == 200

        # Second request should pass
        r2 = client.get("/test-endpoint")
        assert r2.status_code == 200

        # Third request should exceed limit (429)
        r3 = client.get("/test-endpoint")
        assert r3.status_code == 429
        assert r3.json()["errors"][0]["code"] == "RATE_LIMIT_EXCEEDED"
