"""Pydantic domain models for the API Gateway."""

from enum import Enum
from pydantic import BaseModel, EmailStr


class RoleEnum(str, Enum):
    """System roles within a tenant."""
    ADMIN = "admin"
    DOCTOR = "doctor"
    RECEPTIONIST = "receptionist"
    VIEWER = "viewer"


class Permission(str, Enum):
    """Available permissions for RBAC enforcement."""
    APPOINTMENTS_READ = "appointments:read"
    APPOINTMENTS_WRITE = "appointments:write"
    APPOINTMENTS_DELETE = "appointments:delete"
    PATIENTS_READ = "patients:read"
    PATIENTS_WRITE = "patients:write"
    PATIENTS_CLINICAL_READ = "patients:clinical:read"
    PATIENTS_CLINICAL_WRITE = "patients:clinical:write"
    MEDICAL_SUMMARIES_WRITE = "medical_summaries:write"
    BILLING_READ = "billing:read"
    BILLING_WRITE = "billing:write"
    TEAM_MANAGE = "team:manage"
    AI_CHAT = "ai:chat"


class TenantContext(BaseModel):
    """Verified tenant context extracted from the JWT."""
    user_id: str
    tenant_id: str
    role: str
    email: str | None = None
    tier: str = "free"
