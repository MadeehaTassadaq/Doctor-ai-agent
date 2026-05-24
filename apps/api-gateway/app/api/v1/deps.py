"""FastAPI dependencies for auth, RBAC, and DB sessions."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.middleware.rbac import require_permission


async def get_tenant_context(request: Request) -> dict:
    """Extract verified tenant context from request state (set by auth middleware)."""
    user_id = getattr(request.state, "user_id", None)
    tenant_id = getattr(request.state, "tenant_id", None)
    user_role = getattr(request.state, "user_role", None)

    if not user_id or not tenant_id:
        raise HTTPException(status_code=401, detail="Missing authentication context")

    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": user_role,
        "email": getattr(request.state, "user_email", ""),
        "tier": getattr(request.state, "tier", "free"),
    }
