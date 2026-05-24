"""Authentication middleware: verifies JWT and extracts user context."""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, Request, Response
from starlette.responses import JSONResponse

from app.middleware.auth import verify_token

logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = frozenset({
    "/health",
    "/health/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
})


def _error_response(status_code: int, detail: str, err_type: str) -> JSONResponse:
    """Build a RFC 9457 Problem Details response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "type": f"https://api.doctorai.com/errors/{err_type}",
            "title": detail,
            "status": status_code,
            "detail": detail,
        },
    )


async def auth_middleware(request: Request, call_next):
    """Verifies JWT and sets request.state with user context.

    Catches HTTPException internally and returns JSONResponse directly
    to avoid Starlette's BaseHTTPMiddleware ExceptionGroup wrapping.
    """
    try:
        # Add request ID to every request
        request.state.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        start_time = datetime.now(timezone.utc)

        # Skip auth for public paths
        if request.url.path in PUBLIC_PATHS:
            response = await call_next(request)
            _add_common_headers(response, request, start_time)
            return response

        # Skip auth for OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            response = await call_next(request)
            _add_common_headers(response, request, start_time)
            return response

        # Skip auth for the webhook endpoint (verifies via HMAC instead)
        if request.url.path == "/api/v1/auth/webhook":
            response = await call_next(request)
            _add_common_headers(response, request, start_time)
            return response

        # Extract token
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return _error_response(401, "Authorization header must be: Bearer <token>", "missing-token")

        token = auth_header.split("Bearer ")[-1].strip()

        # Verify token via JWKS
        payload = await verify_token(token)
        if payload is None:
            logger.warning("token_verification_failed", extra={"path": request.url.path})
            return _error_response(401, "Token is invalid or expired. Please refresh.", "invalid-token")

        # Extract claims from verified JWT
        app_metadata = payload.get("app_metadata", {})
        tenant_id = app_metadata.get("tenant_id")
        role = app_metadata.get("role", "viewer")

        if not tenant_id:
            return _error_response(403, "User is not associated with any tenant.", "no-tenant")

        # Set request state for downstream middleware and routes
        request.state.user_id = payload.get("sub")
        request.state.tenant_id = tenant_id
        request.state.user_role = role
        request.state.user_email = payload.get("email", "")
        request.state.tier = app_metadata.get("tier", "free")

        # Log auth event (audit)
        logger.info(
            "auth_event",
            extra={
                "event": "request_authenticated",
                "user_id": request.state.user_id,
                "tenant_id": request.state.tenant_id,
                "role": request.state.user_role,
                "path": request.url.path,
                "method": request.method,
                "request_id": request.state.request_id,
            },
        )

        response = await call_next(request)
        _add_common_headers(response, request, start_time)
        return response

    except HTTPException as exc:
        # Catch any HTTPExceptions from downstream and convert to JSON
        if isinstance(exc.detail, dict) and "type" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content={**exc.detail, "instance": str(request.url.path)},
                headers=exc.headers,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"https://api.doctorai.com/errors/http-{exc.status_code}",
                "title": str(exc.detail),
                "status": exc.status_code,
                "detail": str(exc.detail),
                "instance": str(request.url.path),
            },
        )


def _add_common_headers(response: Response, request: Request, start_time: datetime) -> None:
    """Add common response headers."""
    response.headers["X-Request-ID"] = getattr(request.state, "request_id", "")

    # Add rate limit headers if set by rate limiter
    remaining = getattr(request.state, "rate_limit_remaining", None)
    limit = getattr(request.state, "rate_limit_limit", None)
    if remaining is not None:
        response.headers["X-RateLimit-Remaining"] = str(remaining)
    if limit is not None:
        response.headers["X-RateLimit-Limit"] = str(limit)
