"""Tests for medical record endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import MedicalRecord, Patient

_NOW = datetime.now(timezone.utc)

from app.db.session import get_db_session
from app.repositories.patient_repo import PatientRepository


@pytest.mark.asyncio
async def test_list_records_requires_auth(client):
    """GET /api/v1/patients/{id}/records should reject without auth."""
    response = await client.get("/api/v1/patients/some-id/records")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_records_patient_not_found(client, auth_headers, mock_db_session):
    """GET should return 404 if parent patient doesn't exist."""
    with patch.object(PatientRepository, "get_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.get(
            "/api/v1/patients/550e8400-e29b-41d4-a716-446655440099/records",
            headers=auth_headers,
        )
        assert response.status_code == 404

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_records_returns_paginated(client, auth_headers, mock_db_session):
    """GET should return a paginated records list."""
    patient_id = "550e8400-e29b-41d4-a716-446655440100"
    mock_patient = Patient(id=patient_id, tenant_id="tenant-1", first_name="John", last_name="Doe", created_by="user-1", created_at=_NOW, updated_at=_NOW)

    with (
        patch.object(PatientRepository, "get_by_id", new_callable=AsyncMock) as mock_get,
        patch.object(PatientRepository, "list_records", new_callable=AsyncMock) as mock_list,
    ):
        mock_get.return_value = mock_patient
        mock_list.return_value = ([], None)

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.get(
            f"/api/v1/patients/{patient_id}/records",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "next_cursor" in data
        assert "has_more" in data

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_records_filter_by_type(client, auth_headers, mock_db_session):
    """GET should accept record_type filter."""
    patient_id = "550e8400-e29b-41d4-a716-446655440101"
    mock_patient = Patient(id=patient_id, tenant_id="tenant-1", first_name="John", last_name="Doe", created_by="user-1", created_at=_NOW, updated_at=_NOW)

    with (
        patch.object(PatientRepository, "get_by_id", new_callable=AsyncMock) as mock_get,
        patch.object(PatientRepository, "list_records", new_callable=AsyncMock) as mock_list,
    ):
        mock_get.return_value = mock_patient
        mock_list.return_value = ([], None)

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.get(
            f"/api/v1/patients/{patient_id}/records?record_type=diagnosis",
            headers=auth_headers,
        )
        assert response.status_code == 200
        mock_list.assert_called_once()
        kwargs = mock_list.call_args.kwargs
        assert kwargs.get("record_type") == "diagnosis"

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_record_validates_fields(client, auth_headers):
    """POST should reject invalid field values."""
    response = await client.post(
        "/api/v1/patients/some-id/records",
        headers=auth_headers,
        json={"title": "", "record_type": "invalid_type"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_record_success(client, auth_headers, mock_db_session):
    """POST should create and return a new medical record."""
    patient_id = "550e8400-e29b-41d4-a716-446655440102"
    mock_patient = Patient(id=patient_id, tenant_id="tenant-1", first_name="John", last_name="Doe", created_by="user-1", created_at=_NOW, updated_at=_NOW)

    mock_record = MedicalRecord(
        id="660e8400-e29b-41d4-a716-446655440001",
        tenant_id="tenant-1",
        patient_id=patient_id,
        record_type="diagnosis",
        title="Seasonal Allergies",
        description="Patient presents with allergy symptoms",
        diagnosis="Allergic rhinitis (J30.9)",
        created_by="user-1",
        created_at=_NOW,
        updated_at=_NOW,
    )

    with (
        patch.object(PatientRepository, "get_by_id", new_callable=AsyncMock) as mock_get,
        patch.object(PatientRepository, "create_record", new_callable=AsyncMock) as mock_create,
    ):
        mock_get.return_value = mock_patient
        mock_create.return_value = mock_record

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.post(
            f"/api/v1/patients/{patient_id}/records",
            headers=auth_headers,
            json={
                "record_type": "diagnosis",
                "title": "Seasonal Allergies",
                "description": "Patient presents with allergy symptoms",
                "diagnosis": "Allergic rhinitis (J30.9)",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["record_type"] == "diagnosis"
        assert data["title"] == "Seasonal Allergies"

        test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_record_patient_not_found(client, auth_headers, mock_db_session):
    """POST should return 404 if parent patient doesn't exist."""
    with patch.object(PatientRepository, "get_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        from app.main import app as test_app
        test_app.dependency_overrides[get_db_session] = lambda: mock_db_session

        response = await client.post(
            "/api/v1/patients/550e8400-e29b-41d4-a716-446655440099/records",
            headers=auth_headers,
            json={"title": "Test Record", "record_type": "note"},
        )
        assert response.status_code == 404

        test_app.dependency_overrides.clear()
