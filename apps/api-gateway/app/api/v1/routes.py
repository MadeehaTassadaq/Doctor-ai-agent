"""API v1 route definitions for the gateway."""

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db_session
from app.models.schemas import HealthResponse, InviteCreateRequest, ReadinessResponse, SignupEvent, WebhookResponse
from app.services.auth_service import AuthService

router = APIRouter()
webhook_router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Health ────────────────────────────────────────────────────────────────────


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "healthy"}


@router.get("/health/ready")
async def readiness(db: AsyncSession = Depends(get_db_session)) -> ReadinessResponse:
    """Readiness check — verifies database connectivity."""
    db_ok = True
    try:
        await db.execute("SELECT 1")
    except Exception:
        db_ok = False
    return ReadinessResponse(
        status="ready" if db_ok else "degraded",
        database=db_ok,
    )


# ─── Auth Webhook ──────────────────────────────────────────────────────────────


async def verify_supabase_webhook(request: Request) -> bytes:
    """Verify HMAC signature from Supabase Auth webhook."""
    body = await request.body()
    signature = request.headers.get("x-supabase-signature", "")
    if not settings.supabase_webhook_secret:
        logger.warning("SUPABASE_WEBHOOK_SECRET not set — skipping webhook verification")
        return body

    expected = hmac.new(
        settings.supabase_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    return body


@webhook_router.post("/api/v1/auth/webhook", include_in_schema=False)
async def handle_auth_webhook(request: Request, db: AsyncSession = Depends(get_db_session)) -> WebhookResponse:
    """Handle Supabase Auth webhook events (user.signup).

    For invite-only mode:
    - Checks if the signing-up user has a pending invite
    - Activates the team member and sets app_metadata
    """
    body = await verify_supabase_webhook(request)
    event = SignupEvent.model_validate_json(body)

    if event.type != "user.signup":
        return WebhookResponse(status="ignored", message=f"Unhandled event type: {event.type}")

    service = AuthService(db)
    try:
        result = await service.handle_signup(
            user_id=event.user_id,
            email=event.email,
            user_metadata=event.user_metadata,
        )
        return WebhookResponse(
            status="ok",
            tenant_id=result.get("tenant_id"),
            message=f"User {result.get('status')} successfully",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Webhook processing failed")
        return WebhookResponse(status="error", message=str(e))


# ─── Team Management ───────────────────────────────────────────────────────────


@router.post("/api/v1/team/invite")
async def create_invite(
    body: InviteCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Create a team member invitation (admin only)."""
    tenant_id: str = getattr(request.state, "tenant_id", "")
    user_role: str = getattr(request.state, "user_role", "")

    service = AuthService(db)
    invite = await service.create_invite(
        tenant_id=tenant_id,
        email=str(body.email),
        role=body.role,
        requested_by_role=user_role,
    )
    return invite


# ─── Internal Token Verification ───────────────────────────────────────────────


@router.post("/api/v1/internal/verify")
async def verify_internal_request(request: Request) -> dict[str, Any]:
    """Verify an internal request's auth token.

    Used by other services to validate requests coming through the gateway.
    For MVP, validates a shared internal token sent in headers.
    """
    internal_token = request.headers.get("X-Internal-Auth", "")
    if not internal_token:
        raise HTTPException(status_code=401, detail="Missing internal auth token")

    if not hmac.compare_digest(internal_token, settings.internal_auth_token):
        raise HTTPException(status_code=401, detail="Invalid internal auth token")

    return {
        "valid": True,
        "tenant_id": getattr(request.state, "tenant_id", ""),
        "user_id": getattr(request.state, "user_id", ""),
        "role": getattr(request.state, "user_role", ""),
    }
