"""Tests for authentication middleware and JWT verification."""

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_public_paths_do_not_require_auth(client):
    """Public paths should be accessible without a token."""
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_protected_path_rejects_no_token(client):
    """Protected paths should return 401 without Authorization header."""
    response = await client.get("/api/v1/team/invite")
    assert response.status_code == 401
    data = response.json()
    assert "type" in data
    assert data["status"] == 401


@pytest.mark.asyncio
async def test_protected_path_rejects_bad_token(client):
    """Protected paths should return 401 with an invalid token."""
    response = await client.get(
        "/api/v1/team/invite",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_bearer_prefix(client):
    """Authorization header without Bearer prefix should return 401."""
    response = await client.get(
        "/api/v1/team/invite",
        headers={"Authorization": "Token invalid"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_error_response_format(client):
    """Error responses should follow RFC 9457 Problem Details format."""
    response = await client.get("/api/v1/team/invite")
    data = response.json()
    assert "type" in data
    assert "title" in data
    assert "status" in data
    assert "detail" in data


@pytest.mark.asyncio
async def test_x_request_id_added_to_response(client):
    """Every response should include X-Request-ID header."""
    response = await client.get("/health")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0
