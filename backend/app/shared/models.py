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
    # NOTE: the legacy `absent_after` field is intentionally removed.
    # Absent now triggers at `start + grace_minutes` — same threshold as
    # late — so the tile and the exceptions panel agree. Kept for
    # backwards-compat with old configs by simply accepting and ignoring.
    absent_after: str | None = None
    # Expected workday length in minutes. Below this on a day with both
    # punches → incomplete-hours exception. Default = 8h.
    full_day_minutes: int = 480
    # WFH weekdays (Mon=0..Sun=6); Prezlab uses Thu, Fri, Sat. Each is a WFH
    # day for any employee whose shift covers it (see `app.shared.wfh`), so
    # WFH is resolved per employee when the roster has shift data, and
    # applied to everyone by weekday when it doesn't (punch-derived roster).
    # On a WFH day office attendance isn't tracked: no Absent/Late/Missing-
    # punch/Incomplete-hours exceptions. Real punches still count toward
    # Present so the office headcount stays accurate.
    wfh_weekdays: list[int] = []


class AttendanceStatus(str, Enum):
    PRESENT = "present"
    LATE = "late"
    ABSENT = "absent"
    UNKNOWN = "unknown"
