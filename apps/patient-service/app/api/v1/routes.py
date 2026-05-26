"""API v1 route definitions for the Patient Service."""

import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_tenant_context
from app.db.session import get_db_session
from app.models.schemas import (
    MedicalRecordCreate,
    MedicalRecordListResponse,
    MedicalRecordResponse,
    PatientCreate,
    PatientListResponse,
    PatientResponse,
    PatientUpdate,
)
from app.services.patient_service import PatientService

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Health ──


@router.get("/health")
async def health() -> dict:
    """Liveness check."""
    return {"status": "healthy"}


@router.get("/health/ready")
async def readiness() -> dict:
    """Readiness check."""
    return {"status": "ready"}


# ── Patient Routes ──


@router.get("/api/v1/patients", response_model=PatientListResponse)
async def list_patients(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> dict:
    """List patients with cursor-based pagination and optional search."""
    context = await get_tenant_context(request)
    service = PatientService(db)
    return await service.list_patients(
        tenant_id=context["tenant_id"],
        limit=limit,
        cursor=cursor,
        search=search,
    )


@router.post("/api/v1/patients", response_model=PatientResponse, status_code=201)
async def create_patient(
    request: Request,
    body: PatientCreate,
    db: AsyncSession = Depends(get_db_session),
) -> PatientResponse:
    """Create a new patient."""
    context = await get_tenant_context(request)
    service = PatientService(db)
    return await service.create_patient(
        data=body,
        tenant_id=context["tenant_id"],
        user_id=context["user_id"],
    )


@router.get("/api/v1/patients/{patient_id}", response_model=PatientResponse)
async def get_patient(
    request: Request,
    patient_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> PatientResponse:
    """Get a single patient by ID."""
    context = await get_tenant_context(request)
    service = PatientService(db)
    return await service.get_patient(patient_id=patient_id, tenant_id=context["tenant_id"])


@router.patch("/api/v1/patients/{patient_id}", response_model=PatientResponse)
async def update_patient(
    request: Request,
    patient_id: str,
    body: PatientUpdate,
    db: AsyncSession = Depends(get_db_session),
) -> PatientResponse:
    """Partially update a patient."""
    context = await get_tenant_context(request)
    service = PatientService(db)
    return await service.update_patient(
        patient_id=patient_id, data=body, tenant_id=context["tenant_id"]
    )


@router.delete("/api/v1/patients/{patient_id}", status_code=204)
async def delete_patient(
    request: Request,
    patient_id: str,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Soft-delete a patient."""
    context = await get_tenant_context(request)
    service = PatientService(db)
    await service.delete_patient(patient_id=patient_id, tenant_id=context["tenant_id"])


# ── Medical Record Routes ──


@router.get("/api/v1/patients/{patient_id}/records", response_model=MedicalRecordListResponse)
async def list_medical_records(
    request: Request,
    patient_id: str,
    db: AsyncSession = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    record_type: str | None = Query(default=None),
) -> dict:
    """List medical records for a patient."""
    context = await get_tenant_context(request)
    service = PatientService(db)
    return await service.list_records(
        patient_id=patient_id,
        tenant_id=context["tenant_id"],
        limit=limit,
        cursor=cursor,
        record_type=record_type,
    )


@router.post(
    "/api/v1/patients/{patient_id}/records",
    response_model=MedicalRecordResponse,
    status_code=201,
)
async def create_medical_record(
    request: Request,
    patient_id: str,
    body: MedicalRecordCreate,
    db: AsyncSession = Depends(get_db_session),
) -> MedicalRecordResponse:
    """Create a medical record for a patient."""
    context = await get_tenant_context(request)
    service = PatientService(db)
    return await service.create_record(
        patient_id=patient_id,
        data=body,
        tenant_id=context["tenant_id"],
        user_id=context["user_id"],
    )
