"""SQLAlchemy ORM models for the Patient Service."""

import uuid
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class Patient(Base):
    """A patient registered at a clinic/hospital."""

    __tablename__ = "patients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    first_name = Column(Text, nullable=False)
    last_name = Column(Text, nullable=False)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    address = Column(Text, nullable=True)
    emergency_contact_name = Column(Text, nullable=True)
    emergency_contact_phone = Column(Text, nullable=True)
    health_card_number = Column(Text, nullable=True)
    insurance_provider = Column(Text, nullable=True)
    insurance_policy_number = Column(Text, nullable=True)
    allergies = Column(ARRAY(Text), nullable=True)
    blood_type = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Patient(id={self.id}, name={self.first_name} {self.last_name})>"


class MedicalRecord(Base):
    """A medical record entry linked to a patient."""

    __tablename__ = "medical_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    patient_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    appointment_id = Column(UUID(as_uuid=True), nullable=True)
    record_type = Column(Text, nullable=False, default="note")
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    diagnosis = Column(Text, nullable=True)
    prescription = Column(JSONB, nullable=True)
    attachments = Column(JSONB, nullable=True, default=list)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<MedicalRecord(id={self.id}, type={self.record_type}, title={self.title})>"
