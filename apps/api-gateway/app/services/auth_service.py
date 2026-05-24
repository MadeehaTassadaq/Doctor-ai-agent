"""Business logic for authentication and tenant management."""

import logging
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.repositories.tenant_repo import TenantRepository

logger = logging.getLogger(__name__)


class AuthService:
    """Handles auth webhook processing, tenant creation, and invite management."""

    def __init__(self, session: AsyncSession):
        self.repo = TenantRepository(session)

    async def handle_signup(self, user_id: str, email: str, user_metadata: dict) -> dict:
        """Handle a new user signup from Supabase Auth webhook.

        Two flows:
        1. Invite flow: user was invited → activate the pending team member
        2. Direct flow: first user signing up → create tenant + roles (for initial setup)
        """
        invite_token = user_metadata.get("invite_token")

        if invite_token:
            # Invite flow: activate the pending invite
            member = await self.repo.get_team_member_by_invite_token(invite_token)
            if not member:
                raise HTTPException(status_code=400, detail="Invalid or expired invite token")

            member = await self.repo.activate_team_member(member.id, user_id)
            if not member:
                raise HTTPException(status_code=400, detail="Could not activate team member")

            # Update user metadata via Supabase Admin API
            await self._update_user_metadata(user_id, {
                "tenant_id": str(member.tenant_id),
                "role": member.role.name if hasattr(member, "role") else "viewer",
            })

            return {"status": "activated", "tenant_id": str(member.tenant_id)}

        # Check if this email has a pending invite (even without token in metadata)
        member = await self.repo.get_team_member_by_email(email)
        if member:
            member = await self.repo.activate_team_member(member.id, user_id)
            if member:
                await self._update_user_metadata(user_id, {
                    "tenant_id": str(member.tenant_id),
                    "role": member.role.name if hasattr(member, "role") else "viewer",
                })
                return {"status": "activated", "tenant_id": str(member.tenant_id)}

            raise HTTPException(status_code=400, detail="Invalid invite for this email")

        # No invite found — reject signup (invite-only mode)
        raise HTTPException(
            status_code=403,
            detail="Sign-up is invite-only. Please ask your clinic admin to invite you.",
        )

    async def create_invite(self, tenant_id: str, email: str, role: str, requested_by_role: str) -> dict:
        """Create a new team member invitation."""
        if requested_by_role != "admin":
            raise HTTPException(status_code=403, detail="Only admins can invite team members")

        if role not in ("admin", "doctor", "receptionist", "viewer"):
            raise HTTPException(status_code=400, detail=f"Invalid role: {role}")

        try:
            invite = await self.repo.create_invite(tenant_id, email, role)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        return {
            "id": str(invite.id),
            "email": invite.invite_email,
            "role": role,
            "invite_token": invite.invite_token,
            "expires_at": None,
        }

    async def _update_user_metadata(self, user_id: str, metadata: dict) -> None:
        """Update a user's app_metadata via Supabase Admin API."""
        if not settings.supabase_service_role_key:
            logger.warning("SUPABASE_SERVICE_ROLE_KEY not set — skipping metadata update")
            return

        project_ref = settings.supabase_project_ref
        url = f"https://{project_ref}.supabase.co/auth/v1/admin/users/{user_id}"
        headers = {
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.put(url, json={"app_metadata": metadata}, headers=headers)
            if response.status_code != 200:
                logger.error("Failed to update user metadata: %s %s", response.status_code, response.text)
