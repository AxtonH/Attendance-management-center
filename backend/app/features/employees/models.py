"""Response models for the employees feature."""

from datetime import datetime

from pydantic import BaseModel


class EmployeeDay(BaseModel):
    """One row in the daily employee table: first and last punch of the day."""

    emp_code: str
    name: str
    punch_in: datetime
    punch_out: datetime | None = None  # None if employee only punched once
    # punch_out - punch_in in whole minutes. None when punch_out is None
    # (single-punch day → no defensible duration to show).
    worked_minutes: int | None = None


class EmployeesTodayResponse(BaseModel):
    date: str
    rows: list[EmployeeDay]
