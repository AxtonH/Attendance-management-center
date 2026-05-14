"""Response models for the dashboard feature."""

from enum import Enum

from pydantic import BaseModel, Field


# ---------- Overview tile ----------


class OverviewResponse(BaseModel):
    date: str
    present: int
    late: int
    # Phase 1: absent is None — we don't know who was expected without a roster.
    # Phase 2 (Odoo roster) will populate it.
    absent: int | None = None


# ---------- Exceptions panel ----------


class ExceptionSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExceptionTag(str, Enum):
    ABSENT = "absent"
    LATE = "late"
    # Employee had exactly one punch on a prior working day — couldn't tell
    # if it was the check-in or check-out, so the timesheet is incomplete.
    MISSING_PUNCH = "missing_punch"
    # Both punches present on a prior working day, but punch_out - punch_in
    # was below the configured full-day length.
    INCOMPLETE_HOURS = "incomplete_hours"
    PATTERN = "pattern"
    REVIEW = "review"


class ExceptionItem(BaseModel):
    emp_code: str
    name: str
    department: str
    severity: ExceptionSeverity
    tag: ExceptionTag
    detail: str = Field(..., description="Human-readable explanation, e.g. 'Late 18 min'")


class ExceptionsResponse(BaseModel):
    date: str
    total: int
    items: list[ExceptionItem]


# ---------- Departments roll-up ----------


class DepartmentRollup(BaseModel):
    name: str
    # Roster size for this department on this day (after WFH/working-day
    # filters). The denominator the UI shows: "present / expected".
    expected: int
    present: int
    late: int
    absent: int


class DepartmentsResponse(BaseModel):
    date: str
    departments: list[DepartmentRollup]


# ---------- Arrival histogram ----------


class ArrivalBucket(BaseModel):
    label: str  # e.g. "08:00"
    count: int


class ArrivalsResponse(BaseModel):
    date: str
    bucket_minutes: int
    buckets: list[ArrivalBucket]


# ---------- Aggregate (single-call) ----------


class DashboardResponse(BaseModel):
    """Single-call aggregate. One Supabase query feeds every panel.

    Exists alongside the individual /api/* endpoints; those stay for
    single-panel refreshes and debugging.
    """

    date: str
    overview: OverviewResponse
    exceptions: ExceptionsResponse
    arrivals: ArrivalsResponse
    departments: DepartmentsResponse
