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


class EmployeeWeekDay(BaseModel):
    """One day's worth of punches for an employee in the weekly view."""

    date: str  # ISO date — child rows render this themselves
    punch_in: datetime
    punch_out: datetime | None = None
    worked_minutes: int | None = None


class EmployeeWeek(BaseModel):
    """All days an employee punched within the viewed week.

    `days` only contains days they actually punched in (per the design
    decision: hide weekends / off-days). `total_*` are sums across `days`.
    `expected_*` reflect the schedule, not the punches: working days on
    the employee's calendar that aren't WFH, times the full-day length.
    """

    emp_code: str
    name: str
    days_worked: int
    expected_days: int  # in-office workdays this week (excludes WFH + off-days)
    total_worked_minutes: int  # sum of `days[*].worked_minutes` (None days = 0)
    expected_minutes: int  # expected_days * full_day_minutes
    days: list[EmployeeWeekDay]


class EmployeesWeekResponse(BaseModel):
    range_start: str
    range_end: str
    rows: list[EmployeeWeek]
