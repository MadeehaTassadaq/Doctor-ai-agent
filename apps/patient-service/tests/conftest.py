"""Test fixtures for the Patient Service."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db.session import get_db_session
from app.main import create_app


@pytest.fixture
def app():
    """Create a fresh app instance for testing."""
    return create_app()


@pytest.fixture
def client(app):
    """Create an async test client."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def auth_headers() -> dict:
    """Headers simulating the API gateway."""
    return {
        "X-Internal-Auth": settings.internal_auth_token,
        "X-Tenant-ID": "tenant-1",
        "X-User-ID": "user-1",
        "X-User-Role": "admin",
    }


@pytest.fixture
def mock_db_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session
