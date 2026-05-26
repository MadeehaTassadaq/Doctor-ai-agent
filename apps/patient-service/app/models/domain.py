"""Pydantic domain models and enums for the Patient Service."""

from enum import Enum


class Gender(str, Enum):
    """Patient gender options."""
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class BloodType(str, Enum):
    """Blood type options."""
    A_POSITIVE = "A+"
    A_NEGATIVE = "A-"
    B_POSITIVE = "B+"
    B_NEGATIVE = "B-"
    AB_POSITIVE = "AB+"
    AB_NEGATIVE = "AB-"
    O_POSITIVE = "O+"
    O_NEGATIVE = "O-"


class RecordType(str, Enum):
    """Medical record type options."""
    NOTE = "note"
    DIAGNOSIS = "diagnosis"
    LAB_RESULT = "lab_result"
    PRESCRIPTION = "prescription"
    IMAGING = "imaging"


class PaginatedResponse:
    """Generic paginated response helper."""
    pass
