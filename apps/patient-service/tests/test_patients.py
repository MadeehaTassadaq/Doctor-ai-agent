"""Tests for patient CRUD endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import Patient

_NOW = datetime.now(timezone.utc)
from app.db.session import get_db_session
from app.repositories.patient_repo import PatientRepository


@pytest.mark.asyncio
async def test_list_patients_requires_auth(client):
    """GET /api/v1/patients should reject requests without internal auth."""
    response = await client.get("/api/v1/patients")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_patients_requires_valid_token(client):
    """GET /api/v1/patients should reject requests with invalid internal auth."""
    response = await client.get(
        "/api/v1/patients",
        headers={"X-Internal-Auth": "invalid-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_check_does_not_require_auth(client):
    """GET /health should be accessible without internal auth."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_list_patients_returns_paginated_response(client, auth_headers, mock_db_session):
    """GET /api/v1/patients should return a paginated list."""
    with patch.object(PatientRepository, "list_patients", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ([], None)

        async def override_dependency():
            return mock_db_session

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = override_dependency

        response = await client.get("/api/v1/patients", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "next_cursor" in data
        assert "has_more" in data

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_patients_with_search(client, auth_headers, mock_db_session):
    """GET /api/v1/patients should accept search query parameter."""
    with patch.object(PatientRepository, "list_patients", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ([], None)

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.get(
            "/api/v1/patients?search=John",
            headers=auth_headers,
        )
        assert response.status_code == 200

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_patient_returns_patient(client, auth_headers, mock_db_session):
    """GET /api/v1/patients/{id} should return a patient."""
    patient_id = "550e8400-e29b-41d4-a716-446655440000"

    mock_patient = Patient(
        id=patient_id,
        tenant_id="tenant-1",
        first_name="John",
        last_name="Doe",
        created_by="user-1",
        created_at=_NOW,
        updated_at=_NOW,
    )

    with patch.object(PatientRepository, "get_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_patient

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.get(f"/api/v1/patients/{patient_id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["first_name"] == "John"
        assert data["last_name"] == "Doe"

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_patient_not_found(client, auth_headers, mock_db_session):
    """GET /api/v1/patients/{id} should return 404 for non-existent patient."""
    with patch.object(PatientRepository, "get_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.get(
            "/api/v1/patients/550e8400-e29b-41d4-a716-446655440000",
            headers=auth_headers,
        )
        assert response.status_code == 404

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_patient_validates_fields(client, auth_headers):
    """POST /api/v1/patients should reject invalid field values."""
    response = await client.post(
        "/api/v1/patients",
        headers=auth_headers,
        json={"first_name": "", "last_name": "", "gender": "invalid"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_patient_success(client, auth_headers, mock_db_session):
    """POST /api/v1/patients should create and return a new patient."""
    patient_id = "550e8400-e29b-41d4-a716-446655440001"

    mock_patient = Patient(
        id=patient_id,
        tenant_id="tenant-1",
        first_name="John",
        last_name="Doe",
        gender="male",
        created_by="user-1",
        created_at=_NOW,
        updated_at=_NOW,
    )

    with (
        patch.object(PatientRepository, "count_by_health_card", new_callable=AsyncMock) as mock_count,
        patch.object(PatientRepository, "create", new_callable=AsyncMock) as mock_create,
    ):
        mock_count.return_value = 0
        mock_create.return_value = mock_patient

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.post(
            "/api/v1/patients",
            headers=auth_headers,
            json={"first_name": "John", "last_name": "Doe", "gender": "male"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["first_name"] == "John"
        assert data["last_name"] == "Doe"
        assert data["gender"] == "male"

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_patient_success(client, auth_headers, mock_db_session):
    """PATCH /api/v1/patients/{id} should update and return the patient."""
    patient_id = "550e8400-e29b-41d4-a716-446655440002"

    original_patient = Patient(
        id=patient_id,
        tenant_id="tenant-1",
        first_name="John",
        last_name="Doe",
        phone="+1234567890",
        created_by="user-1",
        created_at=_NOW,
        updated_at=_NOW,
    )

    with (
        patch.object(PatientRepository, "get_by_id", new_callable=AsyncMock) as mock_get,
        patch.object(PatientRepository, "update", new_callable=AsyncMock) as mock_update,
    ):
        mock_get.return_value = original_patient
        mock_update.return_value = original_patient

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.patch(
            f"/api/v1/patients/{patient_id}",
            headers=auth_headers,
            json={"phone": "+1987654321"},
        )
        assert response.status_code == 200

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_patient_success(client, auth_headers, mock_db_session):
    """DELETE /api/v1/patients/{id} should soft-delete (return 204)."""
    patient_id = "550e8400-e29b-41d4-a716-446655440003"

    mock_patient = Patient(
        id=patient_id,
        tenant_id="tenant-1",
        first_name="John",
        last_name="Doe",
        created_by="user-1",
        created_at=_NOW,
        updated_at=_NOW,
    )

    with (
        patch.object(PatientRepository, "get_by_id", new_callable=AsyncMock) as mock_get,
        patch.object(PatientRepository, "soft_delete", new_callable=AsyncMock) as mock_delete,
    ):
        mock_get.return_value = mock_patient
        mock_delete.return_value = None

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.delete(f"/api/v1/patients/{patient_id}", headers=auth_headers)
        assert response.status_code == 204

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_patient_not_found(client, auth_headers, mock_db_session):
    """DELETE /api/v1/patients/{id} should return 404 for non-existent patient."""
    with patch.object(PatientRepository, "get_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.delete(
            "/api/v1/patients/550e8400-e29b-41d4-a716-446655440099",
            headers=auth_headers,
        )
        assert response.status_code == 404

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_patient_duplicate_health_card(client, auth_headers, mock_db_session):
    """POST /api/v1/patients should return 409 for duplicate health_card_number."""
    with patch.object(PatientRepository, "count_by_health_card", new_callable=AsyncMock) as mock_count:
        mock_count.return_value = 1

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.post(
            "/api/v1/patients",
            headers=auth_headers,
            json={
                "first_name": "John",
                "last_name": "Doe",
                "health_card_number": "HCN-12345",
            },
        )
        assert response.status_code == 409
        data = response.json()
        assert "resource-conflict" in data.get("detail", {}).get("type", "")

        test_app.dependency_overrides.clear()
