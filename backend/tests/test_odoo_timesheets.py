"""Tests for the Odoo timesheet (full-day leave) repository.

Faked end-to-end via a stub OdooClient — no network. We exercise:
  1. Mapping account.analytic.line rows → {date: {emp_code}}.
  2. The Time-Off task filter and the full-day hours floor.
  3. employee_id (many2one) → emp_code resolution, including misses.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.infra.odoo_client import OdooClient
from app.infra.odoo_timesheets import OdooTimesheetRepository

START = date(2026, 5, 10)
END = date(2026, 5, 12)

# Odoo hr.employee id → our emp_code (the map the employee repo caches).
ID_TO_CODE = {101: "1001", 102: "1002", 103: "1003"}


def _line(
    emp_id: int,
    day: str,
    hours: float,
    task: str = "Time Off",
) -> dict[str, Any]:
    """Build an account.analytic.line row in Odoo's XML-RPC shape."""
    return {
        "employee_id": [emp_id, f"Employee {emp_id}"],
        "task_id": [9, task] if task else False,
        "date": day,
        "unit_amount": hours,
    }


class FakeOdooClient(OdooClient):
    """Returns canned timesheet rows; records the domain it was queried with."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.last_domain: list[Any] | None = None
        self.call_count = 0

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        batch_size: int = 500,
        order: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.call_count += 1
        self.last_domain = domain
        # Return rows verbatim (the repo reads the fields it needs).
        return list(self._rows)


class TestOnLeaveMapping:
    def test_full_day_leave_maps_to_day_and_code(self):
        rows = [
            _line(101, "2026-05-11", 8.0),
            _line(102, "2026-05-12", 8.0),
        ]
        repo = OdooTimesheetRepository(FakeOdooClient(rows))
        result = repo.on_leave_emp_codes_for_range(START, END, ID_TO_CODE)
        assert result == {
            date(2026, 5, 11): frozenset({"1001"}),
            date(2026, 5, 12): frozenset({"1002"}),
        }

    def test_multiple_employees_same_day_grouped(self):
        rows = [
            _line(101, "2026-05-11", 8.0),
            _line(102, "2026-05-11", 8.0),
        ]
        repo = OdooTimesheetRepository(FakeOdooClient(rows))
        result = repo.on_leave_emp_codes_for_range(START, END, ID_TO_CODE)
        assert result == {date(2026, 5, 11): frozenset({"1001", "1002"})}

    def test_partial_day_excluded(self):
        # 4h Time Off is not a full day → not on-leave (stays absent).
        rows = [_line(101, "2026-05-11", 4.0)]
        repo = OdooTimesheetRepository(FakeOdooClient(rows))
        result = repo.on_leave_emp_codes_for_range(START, END, ID_TO_CODE)
        assert result == {}

    def test_eight_or_more_hours_counts(self):
        rows = [
            _line(101, "2026-05-11", 8.0),
            _line(102, "2026-05-12", 9.5),  # >8 still full-day leave
        ]
        repo = OdooTimesheetRepository(FakeOdooClient(rows))
        result = repo.on_leave_emp_codes_for_range(START, END, ID_TO_CODE)
        assert result[date(2026, 5, 11)] == frozenset({"1001"})
        assert result[date(2026, 5, 12)] == frozenset({"1002"})

    def test_non_time_off_task_excluded(self):
        # A full 8h day on a non-Time-Off task is real work, not leave.
        rows = [_line(101, "2026-05-11", 8.0, task="Client Project")]
        repo = OdooTimesheetRepository(FakeOdooClient(rows))
        result = repo.on_leave_emp_codes_for_range(START, END, ID_TO_CODE)
        assert result == {}

    def test_unknown_employee_id_skipped(self):
        # employee_id 999 isn't in our roster map → dropped, not crashed.
        rows = [
            _line(999, "2026-05-11", 8.0),
            _line(101, "2026-05-11", 8.0),
        ]
        repo = OdooTimesheetRepository(FakeOdooClient(rows))
        result = repo.on_leave_emp_codes_for_range(START, END, ID_TO_CODE)
        assert result == {date(2026, 5, 11): frozenset({"1001"})}

    def test_domain_scopes_dates_task_and_hours(self):
        client = FakeOdooClient([])
        repo = OdooTimesheetRepository(client)
        repo.on_leave_emp_codes_for_range(START, END, ID_TO_CODE)
        domain = client.last_domain or []
        # Date window present on both edges.
        assert ("date", ">=", "2026-05-10") in domain
        assert ("date", "<=", "2026-05-12") in domain
        # Task and hours pruned server-side.
        assert ("task_id", "=", "Time Off") in domain
        assert ("unit_amount", ">=", 8.0) in domain
