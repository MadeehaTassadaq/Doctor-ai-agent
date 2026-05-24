"""Tests for the in-memory rate limiter."""

import pytest
from app.middleware.rate_limiter import RateLimiter


@pytest.fixture
def limiter():
    return RateLimiter(limit=5, window_seconds=60)


def test_requests_within_limit(limiter):
    """Requests within the limit should be allowed."""
    for _ in range(5):
        assert limiter.check("tenant-1") is True


def test_requests_exceed_limit(limiter):
    """Requests exceeding the limit should be rejected."""
    for _ in range(5):
        limiter.check("tenant-1")

    assert limiter.check("tenant-1") is False


def test_different_tenants_independent(limiter):
    """Rate limits should be per-tenant."""
    for _ in range(5):
        limiter.check("tenant-1")

    # Tenant 2 should still be allowed
    assert limiter.check("tenant-2") is True


def test_different_scopes_independent(limiter):
    """Rate limits should be per-scope within a tenant."""
    for _ in range(5):
        limiter.check("tenant-1", scope="general")

    # Different scope should still be allowed
    assert limiter.check("tenant-1", scope="ai_chat") is True


def test_custom_limit():
    """Rate limiters should accept custom limits."""
    custom = RateLimiter(limit=2, window_seconds=60)
    assert custom.check("t1") is True
    assert custom.check("t1") is True
    assert custom.check("t1") is False
