"""SQLAlchemy ORM models for the API Gateway domain."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class Tenant(Base):
    """A clinic/hospital organization (multi-tenant root)."""

    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    tier = Column(String(20), default="free", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    roles = relationship("Role", back_populates="tenant", lazy="selectin")
    team_members = relationship("TeamMember", back_populates="tenant", lazy="selectin")


class Role(Base):
    """Role definition within a tenant (RBAC)."""

    __tablename__ = "roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(50), nullable=False)
    permissions = Column(Text, nullable=True)  # JSON string of permission list
    is_system_role = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    tenant = relationship("Tenant", back_populates="roles")


class TeamMember(Base):
    """A user linked to a tenant with a specific role."""

    __tablename__ = "team_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)  # Supabase auth.users id
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)
    invite_token = Column(String(255), unique=True, nullable=True)
    invite_email = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)
    invited_at = Column(DateTime(timezone=True), nullable=True)
    joined_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    tenant = relationship("Tenant", back_populates="team_members")
