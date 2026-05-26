"""Business logic for patient and medical record operations."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MedicalRecord, Patient
from app.models.schemas import (
    MedicalRecordCreate,
    MedicalRecordResponse,
    PatientCreate,
    PatientResponse,
    PatientUpdate,
)
from app.repositories.patient_repo import PatientRepository


class PatientService:
    """Handles patient and medical record business logic."""

    def __init__(self, session: AsyncSession):
        self.repo = PatientRepository(session)

    # ── Patients ──

    async def list_patients(
        self,
        tenant_id: str,
        limit: int = 20,
        cursor: str | None = None,
        search: str | None = None,
    ) -> dict:
        """List patients with pagination."""
        limit = min(max(1, limit), 100)
        patients, next_cursor = await self.repo.list_patients(
            tenant_id=tenant_id,
            limit=limit,
            cursor=cursor,
            search=search,
        )
        return {
            "items": [PatientResponse.model_validate(p) for p in patients],
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        }

    async def get_patient(self, patient_id: str, tenant_id: str) -> PatientResponse:
        """Get a single patient by ID."""
        patient = await self.repo.get_by_id(patient_id, tenant_id)
        if not patient:
            raise HTTPException(
                status_code=404,
                detail={
                    "type": "/errors/not-found",
                    "title": "Patient Not Found",
                    "status": 404,
                    "detail": f"Patient {patient_id} not found in this tenant",
                },
            )
        return PatientResponse.model_validate(patient)

    async def create_patient(self, data: PatientCreate, tenant_id: str, user_id: str) -> PatientResponse:
        """Create a new patient."""
        # Check for duplicate health card number
        if data.health_card_number:
            dup_count = await self.repo.count_by_health_card(tenant_id, data.health_card_number)
            if dup_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "type": "/errors/resource-conflict",
                        "title": "Duplicate Health Card Number",
                        "status": 409,
                        "detail": f"A patient with health card number '{data.health_card_number}' already exists",
                    },
                )

        patient = Patient(
            tenant_id=tenant_id,
            first_name=data.first_name,
            last_name=data.last_name,
            date_of_birth=data.date_of_birth,
            gender=data.gender,
            phone=data.phone,
            email=data.email,
            address=data.address,
            emergency_contact_name=data.emergency_contact_name,
            emergency_contact_phone=data.emergency_contact_phone,
            health_card_number=data.health_card_number,
            insurance_provider=data.insurance_provider,
            insurance_policy_number=data.insurance_policy_number,
            allergies=data.allergies,
            blood_type=data.blood_type,
            notes=data.notes,
            created_by=user_id,
        )
        patient = await self.repo.create(patient)
        return PatientResponse.model_validate(patient)

    async def update_patient(
        self, patient_id: str, data: PatientUpdate, tenant_id: str
    ) -> PatientResponse:
        """Update an existing patient."""
        patient = await self.repo.get_by_id(patient_id, tenant_id)
        if not patient:
            raise HTTPException(
                status_code=404,
                detail={
                    "type": "/errors/not-found",
                    "title": "Patient Not Found",
                    "status": 404,
                    "detail": f"Patient {patient_id} not found in this tenant",
                },
            )

        # Check health card uniqueness if changed
        if data.health_card_number and data.health_card_number != patient.health_card_number:
            dup_count = await self.repo.count_by_health_card(tenant_id, data.health_card_number, exclude_id=patient_id)
            if dup_count > 0:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "type": "/errors/resource-conflict",
                        "title": "Duplicate Health Card Number",
                        "status": 409,
                        "detail": f"A patient with health card number '{data.health_card_number}' already exists",
                    },
                )

        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return PatientResponse.model_validate(patient)

        patient = await self.repo.update(patient, updates)
        return PatientResponse.model_validate(patient)

    async def delete_patient(self, patient_id: str, tenant_id: str) -> None:
        """Soft-delete a patient."""
        patient = await self.repo.get_by_id(patient_id, tenant_id)
        if not patient:
            raise HTTPException(
                status_code=404,
                detail={
                    "type": "/errors/not-found",
                    "title": "Patient Not Found",
                    "status": 404,
                    "detail": f"Patient {patient_id} not found in this tenant",
                },
            )
        await self.repo.soft_delete(patient)

    # ── Medical Records ──

    async def list_records(
        self,
        patient_id: str,
        tenant_id: str,
        limit: int = 20,
        cursor: str | None = None,
        record_type: str | None = None,
    ) -> dict:
        """List medical records for a patient."""
        # Verify patient exists in tenant
        patient = await self.repo.get_by_id(patient_id, tenant_id)
        if not patient:
            raise HTTPException(
                status_code=404,
                detail={
                    "type": "/errors/not-found",
                    "title": "Patient Not Found",
                    "status": 404,
                    "detail": f"Patient {patient_id} not found in this tenant",
                },
            )

        limit = min(max(1, limit), 100)
        records, next_cursor = await self.repo.list_records(
            patient_id=patient_id,
            tenant_id=tenant_id,
            limit=limit,
            cursor=cursor,
            record_type=record_type,
        )
        return {
            "items": [MedicalRecordResponse.model_validate(r) for r in records],
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        }

    async def create_record(
        self, patient_id: str, data: MedicalRecordCreate, tenant_id: str, user_id: str
    ) -> MedicalRecordResponse:
        """Create a new medical record for a patient."""
        # Verify patient exists in tenant
        patient = await self.repo.get_by_id(patient_id, tenant_id)
        if not patient:
            raise HTTPException(
                status_code=404,
                detail={
                    "type": "/errors/not-found",
                    "title": "Patient Not Found",
                    "status": 404,
                    "detail": f"Patient {patient_id} not found in this tenant",
                },
            )

        record = MedicalRecord(
            tenant_id=tenant_id,
            patient_id=patient_id,
            appointment_id=data.appointment_id,
            record_type=data.record_type,
            title=data.title,
            description=data.description,
            diagnosis=data.diagnosis,
            prescription=data.prescription,
            attachments=data.attachments or [],
            created_by=user_id,
        )
        record = await self.repo.create_record(record)
        return MedicalRecordResponse.model_validate(record)
