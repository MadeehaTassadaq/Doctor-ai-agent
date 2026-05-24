"""RBAC enforcement for the API Gateway."""

from fastapi import HTTPException, Request
from typing import Any

# Permission hierarchy (higher number = more privileged)
ROLE_HIERARCHY: dict[str, int] = {
    "admin": 100,
    "doctor": 80,
    "receptionist": 60,
    "viewer": 40,
}

# Permission to allowed roles mapping
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "appointments:read": ["admin", "doctor", "receptionist", "viewer"],
    "appointments:write": ["admin", "doctor", "receptionist"],
    "appointments:delete": ["admin"],
    "patients:read": ["admin", "doctor", "receptionist", "viewer"],
    "patients:write": ["admin", "doctor", "receptionist"],
    "patients:clinical:read": ["admin", "doctor"],
    "patients:clinical:write": ["admin", "doctor"],
    "medical_summaries:write": ["admin", "doctor"],
    "billing:read": ["admin"],
    "billing:write": ["admin"],
    "team:manage": ["admin"],
    "ai:chat": ["admin", "doctor", "receptionist"],
}


def require_permission(permission: str) -> Any:
    """FastAPI dependency: checks if the user has the required permission.

    Usage:
        @router.get("/patients/{id}")
        async def get_patient(
            request: Request,
            _=Depends(require_permission("patients:read")),
        ):
    """
    async def permission_checker(request: Request) -> None:
        user_role: str = getattr(request.state, "user_role", "")
        allowed_roles = ROLE_PERMISSIONS.get(permission, [])

        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail={
                    "type": "https://api.doctorai.com/errors/insufficient-permissions",
                    "title": "Insufficient Permissions",
                    "status": 403,
                    "detail": f"Role '{user_role}' does not have permission '{permission}'",
                },
            )

    return permission_checker
