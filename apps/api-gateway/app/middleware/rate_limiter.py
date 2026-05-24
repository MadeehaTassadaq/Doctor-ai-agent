"""In-memory sliding window rate limiter (MVP single-tier)."""

import time
from collections import defaultdict

from fastapi import HTTPException, Request

# Per-tenant request log: {tenant_id: {scope: [(timestamp, ...)]}}
_request_log: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))


class RateLimiter:
    """Simple in-memory sliding window rate limiter for MVP.

    Uses per-tenant tracking with a sliding window.
    No Redis dependency needed for single-instance MVP.
    Upgrade to Redis-based limiter when scaling horizontally.
    """

    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = limit
        self.window = window_seconds

    def check(self, tenant_id: str, scope: str = "general") -> bool:
        """Check if request is within rate limit. Returns True if allowed."""
        now = time.time()
        window_start = now - self.window

        # Get or create the log for this tenant+scope
        log = _request_log[tenant_id][scope]

        # Remove expired entries
        while log and log[0] < window_start:
            log.pop(0)

        # Check limit
        if len(log) >= self.limit:
            return False

        # Add current request
        log.append(now)
        return True


# Singleton instance (configurable via env vars)
_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the singleton rate limiter."""
    global _rate_limiter
    from app.config import settings as s

    if _rate_limiter is None:
        _rate_limiter = RateLimiter(limit=s.rate_limit_general, window_seconds=s.rate_limit_window_seconds)
    return _rate_limiter


async def rate_limit_middleware(request: Request, call_next):
    """FastAPI middleware for rate limiting."""
    # Skip rate limiting for health checks and docs
    if request.url.path in ("/health", "/health/ready", "/docs", "/redoc", "/openapi.json"):
        return await call_next(request)

    tenant_id: str = getattr(request.state, "tenant_id", "anonymous")
    scope = "general"
    if "/ai/" in request.url.path:
        scope = "ai_chat"
    elif "/auth/" in request.url.path:
        scope = "auth"

    limiter = get_rate_limiter()
    allowed = limiter.check(tenant_id, scope)

    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "type": "https://api.doctorai.com/errors/rate-limited",
                "title": "Rate Limit Exceeded",
                "status": 429,
                "detail": f"Rate limit exceeded for scope: {scope}",
            },
            headers={"Retry-After": "60"},
        )

    response = await call_next(request)
    return response
