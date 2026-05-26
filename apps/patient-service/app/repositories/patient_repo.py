"""Database access layer for patients and medical records."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Select, and_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MedicalRecord, Patient
from app.utils.cursor import decode_cursor, encode_cursor


class PatientRepository:
    """Repository for patient-related database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Patients ──

    async def count_by_health_card(self, tenant_id: str, health_card_number: str, exclude_id: str | None = None) -> int:
        """Check if a health card number is already in use within a tenant."""
        query = select(func.count()).select_from(Patient).where(
            Patient.tenant_id == tenant_id,
            Patient.health_card_number == health_card_number,
            Patient.deleted_at.is_(None),
        )
        if exclude_id:
            query = query.where(Patient.id != exclude_id)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def list_patients(
        self,
        tenant_id: str,
        limit: int = 20,
        cursor: str | None = None,
        search: str | None = None,
        status: str | None = None,
    ) -> tuple[list[Patient], str | None]:
        """List patients with cursor-based pagination and optional search.

        Returns (items, next_cursor).
        """
        query = select(Patient).where(
            Patient.tenant_id == tenant_id,
            Patient.deleted_at.is_(None),
        )

        # Search filter: ILIKE on first_name, last_name, phone, email
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    Patient.first_name.ilike(search_pattern),
                    Patient.last_name.ilike(search_pattern),
                    Patient.phone.ilike(search_pattern),
                    Patient.email.ilike(search_pattern),
                )
            )

        # Cursor pagination
        if cursor:
            cursor_data = decode_cursor(cursor)
            last_id = cursor_data.get("last_id")
            last_sort_value = cursor_data.get("last_sort_value")
            if last_sort_value:
                query = query.where(
                    or_(
                        Patient.last_name > last_sort_value,
                        and_(Patient.last_name == last_sort_value, Patient.id > last_id),
                    )
                )
            elif last_id:
                query = query.where(Patient.id > last_id)

        query = query.order_by(Patient.last_name, Patient.first_name, Patient.id).limit(limit + 1)

        result = await self.session.execute(query)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = encode_cursor(str(last.id), last.last_name)

        return list(rows), next_cursor

    async def get_by_id(self, patient_id: str, tenant_id: str) -> Patient | None:
        """Get a single patient by ID (scoped to tenant)."""
        result = await self.session.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.tenant_id == tenant_id,
                Patient.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create(self, patient: Patient) -> Patient:
        """Create a new patient record."""
        self.session.add(patient)
        await self.session.flush()
        await self.session.refresh(patient)
        return patient

    async def update(self, patient: Patient, updates: dict) -> Patient:
        """Update a patient record with partial data."""
        for key, value in updates.items():
            if value is not None:
                setattr(patient, key, value)
        patient.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(patient)
        return patient

    async def soft_delete(self, patient: Patient) -> None:
        """Soft-delete a patient record."""
        patient.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()

    # ── Medical Records ──

    async def list_records(
        self,
        patient_id: str,
        tenant_id: str,
        limit: int = 20,
        cursor: str | None = None,
        record_type: str | None = None,
    ) -> tuple[list[MedicalRecord], str | None]:
        """List medical records for a patient with cursor-based pagination."""
        query = select(MedicalRecord).where(
            MedicalRecord.patient_id == patient_id,
            MedicalRecord.tenant_id == tenant_id,
            MedicalRecord.deleted_at.is_(None),
        )

        if record_type:
            query = query.where(MedicalRecord.record_type == record_type)

        if cursor:
            cursor_data = decode_cursor(cursor)
            last_id = cursor_data.get("last_id")
            last_sort_value = cursor_data.get("last_sort_value")
            if last_sort_value:
                query = query.where(
                    or_(
                        MedicalRecord.created_at < last_sort_value,
                        and_(MedicalRecord.created_at == last_sort_value, MedicalRecord.id > last_id),
                    )
                )
            elif last_id:
                query = query.where(MedicalRecord.id > last_id)

        query = query.order_by(MedicalRecord.created_at.desc(), MedicalRecord.id).limit(limit + 1)

        result = await self.session.execute(query)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = encode_cursor(str(last.id), str(last.created_at))

        return list(rows), next_cursor

    async def get_record_by_id(self, record_id: str, patient_id: str, tenant_id: str) -> MedicalRecord | None:
        """Get a single medical record by ID."""
        result = await self.session.execute(
            select(MedicalRecord).where(
                MedicalRecord.id == record_id,
                MedicalRecord.patient_id == patient_id,
                MedicalRecord.tenant_id == tenant_id,
                MedicalRecord.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create_record(self, record: MedicalRecord) -> MedicalRecord:
        """Create a new medical record."""
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record
