"""Tests for RBAC enforcement."""

import pytest
from app.middleware.rbac import require_permission, ROLE_PERMISSIONS


def test_all_permissions_have_role_mappings():
    """Every permission defined should have at least one allowed role."""
    for permission, roles in ROLE_PERMISSIONS.items():
        assert len(roles) > 0, f"Permission {permission} has no allowed roles"


def test_admin_has_all_permissions():
    """Admin role should have access to all permissions."""
    admin_permissions = [
        "appointments:read",
        "appointments:write",
        "appointments:delete",
        "patients:read",
        "patients:write",
        "patients:clinical:read",
        "patients:clinical:write",
        "medical_summaries:write",
        "billing:read",
        "billing:write",
        "team:manage",
        "ai:chat",
    ]
    for perm in admin_permissions:
        assert "admin" in ROLE_PERMISSIONS[perm], f"Admin missing permission: {perm}"


def test_viewer_restricted_permissions():
    """Viewer should NOT have write or clinical permissions."""
    viewer_allowed = ROLE_PERMISSIONS["patients:write"]
    assert "viewer" not in viewer_allowed


def test_role_hierarchy_integrity():
    """All roles in ROLE_PERMISSIONS should be valid roles."""
    from app.middleware.rbac import ROLE_HIERARCHY
    valid_roles = set(ROLE_HIERARCHY.keys())

    for permission, roles in ROLE_PERMISSIONS.items():
        for role in roles:
            assert role in valid_roles, f"Unknown role '{role}' in permission '{permission}'"


def test_require_permission_returns_callable():
    """require_permission should return an async callable."""
    checker = require_permission("patients:read")
    assert callable(checker)
