"""SQLAlchemy ORM models for the Doctor Service."""

import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, Integer, Text, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class Doctor(Base):
    """A doctor registered at a clinic/hospital."""

    __tablename__ = "doctors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    team_member_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # TODO(human): choose nullability and indexing
    first_name = Column(Text, nullable=False)
    last_name = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    license_number = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    profile_image_url = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Doctor(id={self.id}, name={self.first_name} {self.last_name})>"


class DoctorSpecialty(Base):
    """A specialty associated with a doctor."""

    __tablename__ = "doctor_specialties"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    specialty = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<DoctorSpecialty(id={self.id}, specialty={self.specialty})>"


class DoctorSchedule(Base):
    """A weekly recurring schedule slot for a doctor."""

    __tablename__ = "doctor_schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    day_of_week = Column(Integer, nullable=False)  # 0=Sunday, 6=Saturday
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_available = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<DoctorSchedule(id={self.id}, day={self.day_of_week}, {self.start_time}-{self.end_time})>"


class DoctorTimeOff(Base):
    """A time-off period for a doctor."""

    __tablename__ = "doctor_time_off"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doctor_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    reason = Column(Text, nullable=True)
    is_approved = Column(Boolean, nullable=False, default=False)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<DoctorTimeOff(id={self.id}, {self.start_date}-{self.end_date})>"
