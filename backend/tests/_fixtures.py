"""Shared test data builders — not pytest fixtures, just plain helpers."""

from datetime import date, datetime

from app.shared.models import Employee, Punch, ShiftRule

RULE = ShiftRule(start="09:00", grace_minutes=15, absent_after="10:30")
DAY = date(2026, 5, 12)
NOW = datetime(2026, 5, 12, 11, 0)


def punch(emp_code: str, hh: int, mm: int, tid: int = 1) -> Punch:
    return Punch(
        transaction_id=tid,
        emp_code=emp_code,
        employee_name=None,
        punch_time=datetime(2026, 5, 12, hh, mm),
        punch_state="0",
    )


def emp(code: str, name: str = "Test") -> Employee:
    # department="" since phase 1 has no department data.
    return Employee(emp_code=code, name=name, department="", active=True)
