"""Pydantic request/response schemas for the Patient Service."""

from datetime import date, datetime

from pydantic import BaseModel, EmailStr, field_validator


# --- Patient Schemas ---


class PatientCreate(BaseModel):
    """Request schema for creating a new patient."""
    first_name: str
    last_name: str
    date_of_birth: date | None = None
    gender: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    health_card_number: str | None = None
    insurance_provider: str | None = None
    insurance_policy_number: str | None = None
    allergies: list[str] | None = None
    blood_type: str | None = None
    notes: str | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_name_length(cls, v: str) -> str:
        if len(v) < 1 or len(v) > 100:
            raise ValueError("Name must be between 1 and 100 characters")
        return v.strip()

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: str | None) -> str | None:
        if v is not None and v not in ("male", "female", "other", "prefer_not_to_say"):
            raise ValueError("Gender must be one of: male, female, other, prefer_not_to_say")
        return v

    @field_validator("blood_type")
    @classmethod
    def validate_blood_type(cls, v: str | None) -> str | None:
        allowed = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")
        if v is not None and v not in allowed:
            raise ValueError(f"Blood type must be one of: {', '.join(allowed)}")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob(cls, v: date | None) -> date | None:
        if v is not None and v >= date.today():
            raise ValueError("Date of birth must be in the past")
        return v

    @field_validator("allergies")
    @classmethod
    def validate_allergies(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) > 50:
            raise ValueError("Maximum 50 allergies allowed")
        return v


class PatientUpdate(BaseModel):
    """Request schema for updating an existing patient (all fields optional)."""
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    health_card_number: str | None = None
    insurance_provider: str | None = None
    insurance_policy_number: str | None = None
    allergies: list[str] | None = None
    blood_type: str | None = None
    notes: str | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def validate_name_length(cls, v: str | None) -> str | None:
        if v is not None and (len(v) < 1 or len(v) > 100):
            raise ValueError("Name must be between 1 and 100 characters")
        return v.strip() if v else v

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: str | None) -> str | None:
        if v is not None and v not in ("male", "female", "other", "prefer_not_to_say"):
            raise ValueError("Gender must be one of: male, female, other, prefer_not_to_say")
        return v

    @field_validator("blood_type")
    @classmethod
    def validate_blood_type(cls, v: str | None) -> str | None:
        allowed = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")
        if v is not None and v not in allowed:
            raise ValueError(f"Blood type must be one of: {', '.join(allowed)}")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob(cls, v: date | None) -> date | None:
        if v is not None and v >= date.today():
            raise ValueError("Date of birth must be in the past")
        return v


class PatientResponse(BaseModel):
    """Response schema for a single patient."""
    id: str
    first_name: str
    last_name: str
    date_of_birth: date | None = None
    gender: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    health_card_number: str | None = None
    insurance_provider: str | None = None
    insurance_policy_number: str | None = None
    allergies: list[str] | None = None
    blood_type: str | None = None
    notes: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatientListResponse(BaseModel):
    """Response schema for paginated patient list."""
    items: list[PatientResponse]
    next_cursor: str | None = None
    has_more: bool = False


# --- Medical Record Schemas ---


class MedicalRecordCreate(BaseModel):
    """Request schema for creating a medical record."""
    appointment_id: str | None = None
    record_type: str = "note"
    title: str
    description: str | None = None
    diagnosis: str | None = None
    prescription: dict | None = None
    attachments: list[dict] | None = None

    @field_validator("title")
    @classmethod
    def validate_title_length(cls, v: str) -> str:
        if len(v) < 1 or len(v) > 200:
            raise ValueError("Title must be between 1 and 200 characters")
        return v.strip()

    @field_validator("record_type")
    @classmethod
    def validate_record_type(cls, v: str) -> str:
        allowed = ("note", "diagnosis", "lab_result", "prescription", "imaging")
        if v not in allowed:
            raise ValueError(f"Record type must be one of: {', '.join(allowed)}")
        return v


class MedicalRecordResponse(BaseModel):
    """Response schema for a medical record."""
    id: str
    patient_id: str
    appointment_id: str | None = None
    record_type: str
    title: str
    description: str | None = None
    diagnosis: str | None = None
    prescription: dict | None = None
    attachments: list[dict] | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MedicalRecordListResponse(BaseModel):
    """Response schema for paginated medical record list."""
    items: list[MedicalRecordResponse]
    next_cursor: str | None = None
    has_more: bool = False
