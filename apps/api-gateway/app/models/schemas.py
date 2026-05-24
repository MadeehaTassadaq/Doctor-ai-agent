"""Pydantic request/response schemas for the API Gateway."""

from datetime import datetime

from pydantic import BaseModel, EmailStr


# --- Auth / Webhook ---

class SignupEvent(BaseModel):
    """Supabase Auth webhook payload for user.signup events."""
    type: str
    user_id: str
    email: str
    user_metadata: dict = {}
    invite_token: str | None = None


class WebhookResponse(BaseModel):
    """Response from the auth webhook handler."""
    status: str
    tenant_id: str | None = None
    message: str | None = None


# --- Invite ---

class InviteCreateRequest(BaseModel):
    """Request to invite a new team member."""
    email: EmailStr
    role: str = "viewer"


class InviteResponse(BaseModel):
    """Response after creating an invitation."""
    id: str
    email: str
    role: str
    invite_token: str
    expires_at: datetime


# --- Team ---

class TeamMemberResponse(BaseModel):
    """Team member details."""
    id: str
    email: str
    role: str
    is_active: bool
    joined_at: datetime | None = None


# --- Health ---

class HealthResponse(BaseModel):
    """Health check response."""
    status: str


class ReadinessResponse(BaseModel):
    """Readiness check response."""
    status: str
    database: bool
