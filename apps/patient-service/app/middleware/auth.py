"""Internal auth middleware for verifying gateway requests."""

import hmac
import logging

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)


async def verify_internal_auth(request: Request, call_next):
    """Middleware: verifies the internal auth token from the API gateway.

    All requests to the patient service MUST come through the API gateway,
    which injects an X-Internal-Auth header with a shared secret.
    """
    # Health endpoints are public (no auth needed)
    if request.url.path in ("/health", "/health/ready"):
        return await call_next(request)

    internal_token = request.headers.get("X-Internal-Auth", "")
    if not internal_token:
        return JSONResponse(
            status_code=401,
            content={
                "type": "/errors/authentication-error",
                "title": "Missing Internal Auth",
                "status": 401,
                "detail": "Missing X-Internal-Auth header",
            },
        )

    if not hmac.compare_digest(internal_token, settings.internal_auth_token):
        return JSONResponse(
            status_code=401,
            content={
                "type": "/errors/authentication-error",
                "title": "Invalid Internal Auth",
                "status": 401,
                "detail": "Invalid internal auth token",
            },
        )

    # Extract context from gateway-injected headers
    request.state.tenant_id = request.headers.get("X-Tenant-ID", "")
    request.state.user_id = request.headers.get("X-User-ID", "")
    request.state.user_role = request.headers.get("X-User-Role", "")

    return await call_next(request)
