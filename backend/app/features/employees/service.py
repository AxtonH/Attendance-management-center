"""Employees feature: pure service functions."""

from datetime import date, datetime
from typing import Mapping

from app.shared.models import Employee, Punch, ShiftRule

from app.features.employees.models import (
    EmployeeDay,
    EmployeeWeek,
    EmployeeWeekDay,
    EmployeesTodayResponse,
    EmployeesWeekResponse,
)

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


def build_employees_week(
    employees: list[Employee],
    punches_by_day: Mapping[date, list[Punch]],
    days: list[date],
    *,
    expected_emp_codes: frozenset[str] | None = None,
    roster_names: Mapping[str, str] = _EMPTY_NAMES,
    rule: ShiftRule | None = None,
    working_emp_codes_by_day: Mapping[date, frozenset[str] | None] | None = None,
) -> EmployeesWeekResponse:
    """One parent row per employee with a child row per day they punched.

    Composition over `build_employees_today`: we call it once per day in
    the range, then group the resulting `EmployeeDay`s by emp_code. That
    means the name-resolution and roster-filter rules stay identical
    between Daily and Weekly views — no logic drift.

    Days an employee didn't punch are simply absent from their child list
    (per the design decision to hide off-days). Employees who never
    punched all week don't appear at all — "1+ entry" filtering happens
    naturally as a side effect.

    Per-employee `expected_days` counts in-office workdays for the week:
    days the schedule covers them MINUS WFH days (Prezlab's Thursday).
    When `rule` and `working_emp_codes_by_day` are not provided the
    expecteds default to 0 — phase-1 behavior, no schedule data.
    """
    # emp_code → {name, days: [EmployeeWeekDay], total_minutes, days_worked}
    by_code: dict[str, dict] = {}

    for day in days:
        day_punches = punches_by_day.get(day, [])
        if not day_punches:
            continue
        per_day = build_employees_today(
            employees,
            day_punches,
            day,
            expected_emp_codes=expected_emp_codes,
            roster_names=roster_names,
        )
        for row in per_day.rows:
            entry = by_code.setdefault(
                row.emp_code,
                {"name": row.name, "days": [], "total_minutes": 0},
            )
            entry["days"].append(
                EmployeeWeekDay(
                    date=day.isoformat(),
                    punch_in=row.punch_in,
                    punch_out=row.punch_out,
                    worked_minutes=row.worked_minutes,
                )
            )
            if row.worked_minutes is not None:
                entry["total_minutes"] += row.worked_minutes

    # Pre-compute the in-office workday set per emp_code in one pass over
    # the week. O(days × employees) but employees here is just the ones
    # we already grouped — tiny.
    expected_days_by_code: dict[str, int] = {}
    if rule is not None and working_emp_codes_by_day is not None:
        wfh = set(rule.wfh_weekdays)
        for day in days:
            if day.weekday() in wfh:
                continue
            working = working_emp_codes_by_day.get(day)
            if working is None:
                continue
            for code in by_code:
                if code in working:
                    expected_days_by_code[code] = (
                        expected_days_by_code.get(code, 0) + 1
                    )

    full_day = rule.full_day_minutes if rule is not None else 0

    rows: list[EmployeeWeek] = []
    for code, entry in by_code.items():
        expected_days = expected_days_by_code.get(code, 0)
        # Days are added in iteration order, which matches `days` ASC.
        # Stable since we never re-sort.
        rows.append(
            EmployeeWeek(
                emp_code=code,
                name=entry["name"],
                days_worked=len(entry["days"]),
                expected_days=expected_days,
                total_worked_minutes=entry["total_minutes"],
                expected_minutes=expected_days * full_day,
                days=entry["days"],
            )
        )

    # Outer sort: emp_code desc, numeric where possible (matches the
    # daily Employees table convention).
    def _sort_key(r: EmployeeWeek) -> tuple[int, int | str]:
        try:
            return (0, -int(r.emp_code))
        except ValueError:
            return (1, r.emp_code)

    rows.sort(key=_sort_key)
    return EmployeesWeekResponse(
        range_start=days[0].isoformat(),
        range_end=days[-1].isoformat(),
        rows=rows,
    )
