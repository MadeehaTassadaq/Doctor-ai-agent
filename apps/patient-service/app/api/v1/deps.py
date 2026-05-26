"""FastAPI dependencies for internal auth and DB sessions."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session


async def get_tenant_context(request: Request) -> dict:
    """Extract verified tenant context from request state (set by auth middleware)."""
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)
    user_role = getattr(request.state, "user_role", None)

    if not tenant_id or not user_id:
        raise HTTPException(status_code=401, detail="Missing authentication context")

    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": user_role,
    }


class TenantContextDeps:
    """Convenience class providing individual dependencies for context fields."""

    @staticmethod
    def tenant_id(context: dict = Depends(get_tenant_context)) -> str:
        return context["tenant_id"]

    @staticmethod
    def user_id(context: dict = Depends(get_tenant_context)) -> str:
        return context["user_id"]

    @staticmethod
    def user_role(context: dict = Depends(get_tenant_context)) -> str:
        return context["role"]
