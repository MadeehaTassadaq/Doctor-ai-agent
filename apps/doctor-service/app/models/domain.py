"""Pydantic domain models and enums for the Doctor Service."""

from datetime import time
from enum import Enum


class DayOfWeek(int, Enum):
    """Day of week (0=Sunday through 6=Saturday)."""
    SUNDAY = 0
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
