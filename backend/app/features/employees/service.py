"""Employees feature: pure service functions."""

from datetime import date, datetime
from typing import Mapping

from app.shared.models import Employee, Punch

from app.features.employees.models import EmployeeDay, EmployeesTodayResponse

_EMPTY_NAMES: Mapping[str, str] = {}


def build_employees_today(
    employees: list[Employee],
    punches: list[Punch],
    day: date,
    *,
    expected_emp_codes: frozenset[str] | None = None,
    roster_names: Mapping[str, str] = _EMPTY_NAMES,
) -> EmployeesTodayResponse:
    """One row per employee: first and last punch of the day.

    punch_out is None when there's only one punch (or every punch is at the
    same minute). This avoids showing a meaningless 'out at same time as in'.

    When `expected_emp_codes` is provided (Odoo roster), only those employees
    appear in the table — keeps this view consistent with the Present/Absent
    tile counts. Names come from `roster_names` (Odoo) when available, then
    from the punch-derived `employees` list (BioTime) as fallback.
    """
    by_code: dict[str, list[datetime]] = {}
    for p in punches:
        if not p.emp_code:
            continue
        if expected_emp_codes is not None and p.emp_code not in expected_emp_codes:
            continue
        by_code.setdefault(p.emp_code, []).append(p.punch_time)

    biotime_names = {e.emp_code: e.name for e in employees if e.active}

    rows: list[EmployeeDay] = []
    for code, times in by_code.items():
        odoo_name = roster_names.get(code)
        if odoo_name:
            name = odoo_name
        elif roster_names:
            # Odoo configured but no name for this code → drop the row,
            # same rule as the exceptions panel.
            continue
        elif code in biotime_names:
            name = biotime_names[code]
        else:
            continue
        times.sort()
        first = times[0]
        last = times[-1]
        punch_out = last if last != first else None
        worked_minutes = (
            int((punch_out - first).total_seconds() // 60)
            if punch_out is not None
            else None
        )
        rows.append(
            EmployeeDay(
                emp_code=code,
                name=name,
                punch_in=first,
                punch_out=punch_out,
                worked_minutes=worked_minutes,
            )
        )
    return EmployeesTodayResponse(date=day.isoformat(), rows=rows)
