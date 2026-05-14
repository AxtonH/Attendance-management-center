"""Cross-feature domain types.

Anything used by two or more features lives here. Feature-specific response
models live alongside their feature's service code.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


# ---------- Source data ----------


class Punch(BaseModel):
    """A single punch event, mirrored from BioTime via Supabase."""

    transaction_id: int
    emp_code: str | None = None
    employee_name: str | None = None
    punch_time: datetime
    punch_state: str | None = None


# ---------- Roster ----------


class Employee(BaseModel):
    emp_code: str
    name: str
    department: str
    active: bool = True


class Department(BaseModel):
    code: str
    name: str


# ---------- Shift rules ----------


class ShiftRule(BaseModel):
    """One shift definition. Phase 1 uses only `default_shift`."""

    start: str  # "HH:MM"
    grace_minutes: int
    absent_after: str  # "HH:MM"
    # Expected workday length in minutes. Below this on a day with both
    # punches → incomplete-hours exception. Default = 8h.
    full_day_minutes: int = 480
    # Weekdays (Mon=0..Sun=6) treated as work-from-home: still a working
    # day, but office attendance is not tracked. No Absent/Late/Missing-
    # punch/Incomplete-hours exceptions fire on these days. Real punches
    # still count toward Present so the office headcount stays accurate.
    # Phase 3 will replace this with per-employee WFH data from Odoo.
    wfh_weekdays: list[int] = []


class AttendanceStatus(str, Enum):
    PRESENT = "present"
    LATE = "late"
    ABSENT = "absent"
    UNKNOWN = "unknown"
