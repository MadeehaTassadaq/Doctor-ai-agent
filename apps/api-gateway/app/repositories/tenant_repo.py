"""Database access layer for tenants, roles, and team members."""

import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Role, TeamMember, Tenant

# Default permissions per role (JSON strings)
ADMIN_PERMISSIONS = (
    '["appointments:read","appointments:write","appointments:delete",'
    '"patients:read","patients:write","patients:clinical:read",'
    '"patients:clinical:write","medical_summaries:write",'
    '"billing:read","billing:write","team:manage","ai:chat"]'
)
DOCTOR_PERMISSIONS = (
    '["appointments:read","appointments:write","patients:read","patients:write",'
    '"patients:clinical:read","patients:clinical:write","medical_summaries:write","ai:chat"]'
)
RECEPTIONIST_PERMISSIONS = (
    '["appointments:read","appointments:write","patients:read","patients:write","ai:chat"]'
)
VIEWER_PERMISSIONS = '["appointments:read","patients:read","patients:clinical:read"]'


class TenantRepository:
    """Repository for tenant-related database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        """Find a tenant by its slug."""
        result = await self.session.execute(select(Tenant).where(Tenant.slug == slug, Tenant.deleted_at.is_(None)))
        return result.scalar_one_or_none()

    async def get_team_member_by_email(self, email: str) -> TeamMember | None:
        """Find a pending team member by invite email."""
        result = await self.session.execute(
            select(TeamMember).where(TeamMember.invite_email == email, TeamMember.is_active.is_(False))
        )
        return result.scalar_one_or_none()

    async def get_team_member_by_invite_token(self, token: str) -> TeamMember | None:
        """Find a team member by invite token."""
        result = await self.session.execute(
            select(TeamMember).where(TeamMember.invite_token == token)
        )
        return result.scalar_one_or_none()

    async def create_invite(self, tenant_id: str, email: str, role_name: str) -> TeamMember:
        """Create a pending team member invitation."""
        # Find the role
        result = await self.session.execute(
            select(Role).where(Role.tenant_id == tenant_id, Role.name == role_name)
        )
        role = result.scalar_one_or_none()
        if not role:
            msg = f"Role '{role_name}' not found for tenant"
            raise ValueError(msg)

        invite = TeamMember(
            tenant_id=tenant_id,
            invite_email=email,
            role_id=role.id,
            invite_token=secrets.token_urlsafe(32),
            is_active=False,
            invited_at=datetime.now(timezone.utc),
        )
        self.session.add(invite)
        await self.session.flush()
        return invite

    async def create_tenant_with_defaults(
        self, name: str, admin_user_id: str, admin_email: str
    ) -> Tenant:
        """Atomically create a tenant with default roles and assign the admin."""
        slug = name.lower().replace(" ", "-")[:50]

        # Create tenant
        tenant = Tenant(name=name, slug=slug)
        self.session.add(tenant)
        await self.session.flush()

        # Create default roles
        default_roles = [
            Role(tenant_id=tenant.id, name="admin", permissions=ADMIN_PERMISSIONS, is_system_role=True),
            Role(tenant_id=tenant.id, name="doctor", permissions=DOCTOR_PERMISSIONS, is_system_role=True),
            Role(tenant_id=tenant.id, name="receptionist", permissions=RECEPTIONIST_PERMISSIONS, is_system_role=True),
            Role(tenant_id=tenant.id, name="viewer", permissions=VIEWER_PERMISSIONS, is_system_role=True),
        ]
        self.session.add_all(default_roles)
        await self.session.flush()

        # Link admin user (for invite flow, check the pending invite first)
        admin_role = default_roles[0]
        team_member = TeamMember(
            tenant_id=tenant.id,
            user_id=admin_user_id,
            role_id=admin_role.id,
            invite_email=admin_email,
            is_active=True,
            invited_at=datetime.now(timezone.utc),
            joined_at=datetime.now(timezone.utc),
        )
        self.session.add(team_member)
        await self.session.flush()

        return tenant

    async def activate_team_member(self, team_member_id: str, user_id: str) -> TeamMember | None:
        """Activate a pending team member after signup."""
        result = await self.session.execute(
            select(TeamMember).where(TeamMember.id == team_member_id)
        )
        member = result.scalar_one_or_none()
        if member and not member.is_active:
            member.is_active = True
            member.user_id = user_id
            member.joined_at = datetime.now(timezone.utc)
            await self.session.flush()
        return member
