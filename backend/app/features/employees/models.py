"""Response models for the employees feature."""

from datetime import datetime

from pydantic import BaseModel


class EmployeeDay(BaseModel):
    """One row in the daily employee table: first and last punch of the day.

    Absent rows (roster employees expected today who never punched) carry
    `absent=True` with null punch fields — the frontend renders dashes and a
    red "Absent" pill, mirroring the dashboard Flags treatment.

    On-leave rows are absences excused by an approved full-day Time Off
    timesheet entry: `on_leave=True`, `absent=False`. The frontend shows a
    pale-blue "On leave" pill instead of the red Absent one.
    """

    emp_code: str
    name: str
    punch_in: datetime | None = None  # None when absent / on leave
    punch_out: datetime | None = None  # None if employee only punched once
    # punch_out - punch_in in whole minutes. None when punch_out is None
    # (single-punch day → no defensible duration to show).
    worked_minutes: int | None = None
    absent: bool = False
    on_leave: bool = False


class EmployeesTodayResponse(BaseModel):
    date: str
    rows: list[EmployeeDay]


class EmployeeWeekDay(BaseModel):
    """One day's worth of punches for an employee in the weekly view.

    Absent days (scheduled in-office days the employee missed) carry
    `absent=True` with null punch fields — same treatment as the daily
    view's absent rows. Days excused by an approved full-day Time Off
    entry carry `on_leave=True` (and `absent=False`) instead.
    """

    date: str  # ISO date — child rows render this themselves
    punch_in: datetime | None = None  # None when absent / on leave
    punch_out: datetime | None = None
    worked_minutes: int | None = None
    absent: bool = False
    on_leave: bool = False


class EmployeeWeek(BaseModel):
    """All days an employee punched within the viewed week.

    `days` contains the days they actually punched plus any scheduled
    in-office days they missed (`absent=True` entries). `days_worked` and
    `total_*` count only the worked days — absent days never contribute.
    `expected_*` reflect the schedule, not the punches: working days on
    the employee's calendar that aren't WFH, times the full-day length.
    """

    emp_code: str
    name: str
    days_worked: int  # worked days only — excludes absent entries
    expected_days: int  # in-office workdays this week (excludes WFH + off-days)
    total_worked_minutes: int  # sum of `days[*].worked_minutes` (None days = 0)
    expected_minutes: int  # expected_days * full_day_minutes
    days: list[EmployeeWeekDay]


class EmployeesWeekResponse(BaseModel):
    range_start: str
    range_end: str
    rows: list[EmployeeWeek]


class EmployeesMonthResponse(BaseModel):
    """Same row shape as the weekly response. Distinct wrapper so the
    monthly endpoint stays self-documenting and the frontend can key its
    queries separately. `expected_days` / `expected_minutes` on each row
    are not meaningful at month scale (variable month length, holidays,
    etc.) and the frontend ignores them in monthly view.
    """

    range_start: str
    range_end: str
    rows: list[EmployeeWeek]
