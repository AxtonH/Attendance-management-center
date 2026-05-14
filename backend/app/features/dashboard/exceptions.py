"""Exception detectors — pure functions, one per exception type.

Each detector takes the data it needs and returns a list of `ExceptionItem`.
No I/O, no datetime.now(): trivially testable, trivially composable.

The composer (`build_exceptions` in service.py) decides ordering, severity
buckets, and filtering. New exception types should land here as a new
function, then get wired into the composer.

Name resolution precedence (used by every detector):
  1. Odoo `display_names` (authoritative — fixes BioTime/Odoo drift).
  2. BioTime employee_name embedded in today's punch (phase-1 fallback).
  3. emp_code as a last resort, only when no Odoo roster is configured.

When Odoo IS configured and a code has no Odoo name, the row is dropped
entirely — that emp_code is not a real employee anyway, so showing it as
"17" or "Unknown" would be misleading.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Mapping

from app.shared import shift_rules
from app.shared.models import AttendanceStatus, Employee, Punch, ShiftRule

from app.features.dashboard.models import (
    ExceptionItem,
    ExceptionSeverity,
    ExceptionTag,
)


def _emp_lookup(employees: Iterable[Employee]) -> dict[str, Employee]:
    """Active-only emp_code → Employee map for display fields."""
    return {e.emp_code: e for e in employees if e.active}


def _filter_roster(
    codes: Iterable[str],
    expected: frozenset[str] | None,
) -> list[str]:
    """Drop emp_codes not on the Odoo roster (when one is provided)."""
    if expected is None:
        return list(codes)
    return [c for c in codes if c in expected]


def _resolve_name(
    code: str,
    roster_names: Mapping[str, str],
    fallback_employee: Employee | None,
) -> str | None:
    """Look up a display name with the Odoo→BioTime→code precedence.

    Returns None when Odoo is configured (`roster_names` non-empty) but this
    code isn't in it — the caller should then skip the row entirely.
    """
    odoo_name = roster_names.get(code)
    if odoo_name:
        return odoo_name
    if roster_names:
        # Odoo configured but no match for this code → not a real employee.
        return None
    if fallback_employee is not None and fallback_employee.name:
        return fallback_employee.name
    return code


_EMPTY_NAMES: Mapping[str, str] = {}


def detect_late(
    employees: list[Employee],
    first_punches: dict[str, datetime],
    rule: ShiftRule,
    day: date,
    now: datetime,
    *,
    expected_emp_codes: frozenset[str] | None = None,
    roster_names: Mapping[str, str] = _EMPTY_NAMES,
) -> list[tuple[int, ExceptionItem]]:
    """Late punchers. Returns (minutes_late, item) pairs so the composer can sort."""
    if day.weekday() in rule.wfh_weekdays:
        return []
    lookup = _emp_lookup(employees)
    out: list[tuple[int, ExceptionItem]] = []
    for code in _filter_roster(first_punches.keys(), expected_emp_codes):
        first = first_punches[code]
        if shift_rules.classify(first, rule, day, now=now) != AttendanceStatus.LATE:
            continue
        emp = lookup.get(code)
        name = _resolve_name(code, roster_names, emp)
        if name is None:
            continue
        mins = shift_rules.minutes_late(first, rule, day)
        severity = ExceptionSeverity.MEDIUM if mins >= 15 else ExceptionSeverity.LOW
        out.append((
            mins,
            ExceptionItem(
                emp_code=code,
                name=name,
                department=(emp.department if emp else "") or "",
                severity=severity,
                tag=ExceptionTag.LATE,
                detail=f"Late {mins} min",
            ),
        ))
    return out


def detect_absent(
    employees: list[Employee],
    first_punches: dict[str, datetime],
    rule: ShiftRule,
    day: date,
    now: datetime,
    *,
    expected_emp_codes: frozenset[str] | None,
    roster_names: Mapping[str, str] = _EMPTY_NAMES,
    working_emp_codes: frozenset[str] | None = None,
) -> list[ExceptionItem]:
    """Roster employees with no punch today, once the absent cutoff has passed.

    Requires `expected_emp_codes` — without a roster we don't know who was
    expected, so we can't list missing people. Pre-cutoff we don't list
    anyone either (might still arrive).

    When `working_emp_codes` is provided, only employees whose schedule
    covers `day` are considered — someone whose calendar is Mon–Fri won't
    be flagged absent on a Sunday.
    """
    if expected_emp_codes is None:
        return []
    if day.weekday() in rule.wfh_weekdays:
        return []
    if now < shift_rules.absent_cutoff_dt(rule, day):
        return []
    roster = expected_emp_codes
    if working_emp_codes is not None:
        roster = roster & working_emp_codes
    lookup = _emp_lookup(employees)
    punched = set(first_punches.keys())
    out: list[ExceptionItem] = []
    for code in roster - punched:
        emp = lookup.get(code)
        name = _resolve_name(code, roster_names, emp)
        if name is None:
            continue
        out.append(
            ExceptionItem(
                emp_code=code,
                name=name,
                department=(emp.department if emp else "") or "",
                severity=ExceptionSeverity.HIGH,
                tag=ExceptionTag.ABSENT,
                detail="No punch today",
            )
        )
    return out


def _format_hours(minutes: int) -> str:
    """Render whole minutes as e.g. '6h 32m'."""
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m"


def detect_prev_day_incomplete_hours(
    employees: list[Employee],
    prev_punches: list[Punch],
    prev_day: date | None,
    rule: ShiftRule,
    *,
    expected_emp_codes: frozenset[str] | None = None,
    roster_names: Mapping[str, str] = _EMPTY_NAMES,
    working_emp_codes_prev_day: frozenset[str] | None = None,
) -> list[ExceptionItem]:
    """Employees whose worked minutes on the prior working day fell short of full_day_minutes.

    Mirrors missing-punch — same input payload, same roster/name plumbing —
    so wiring it into the composer costs nothing extra. Mutually exclusive
    with missing-punch by construction: we only fire when there are at least
    two punches and the duration is computable.

    Worked minutes = last_punch - first_punch (gross, no break deduction).
    Matches what the Employees table shows, so the two views agree.
    """
    if not prev_punches or prev_day is None:
        return []
    if prev_day.weekday() in rule.wfh_weekdays:
        return []
    by_code: dict[str, list[datetime]] = {}
    biotime_names: dict[str, str] = {}
    for p in prev_punches:
        if not p.emp_code:
            continue
        by_code.setdefault(p.emp_code, []).append(p.punch_time)
        if p.employee_name and p.emp_code not in biotime_names:
            biotime_names[p.emp_code] = p.employee_name

    lookup = _emp_lookup(employees)
    # Apply working-day filter ahead of the roster filter: an employee
    # whose schedule didn't cover prev_day shouldn't be flagged even if
    # they happen to have one punch (it's their day off).
    effective_roster = expected_emp_codes
    if effective_roster is not None and working_emp_codes_prev_day is not None:
        effective_roster = effective_roster & working_emp_codes_prev_day
    out: list[ExceptionItem] = []
    for code in _filter_roster(by_code.keys(), effective_roster):
        # Schedule-only filter when no Odoo roster is set.
        if (
            effective_roster is None
            and working_emp_codes_prev_day is not None
            and code not in working_emp_codes_prev_day
        ):
            continue
        times = by_code[code]
        if len(times) < 2:
            # Single punch → that's missing-punch territory, not this one.
            continue
        first = min(times)
        last = max(times)
        worked = int((last - first).total_seconds() // 60)
        if worked >= rule.full_day_minutes:
            continue
        emp = lookup.get(code)
        if emp is None and code in biotime_names:
            emp = Employee(
                emp_code=code, name=biotime_names[code], department="", active=True
            )
        name = _resolve_name(code, roster_names, emp)
        if name is None:
            continue
        out.append(
            ExceptionItem(
                emp_code=code,
                name=name,
                department=(emp.department if emp else "") or "",
                severity=ExceptionSeverity.MEDIUM,
                tag=ExceptionTag.INCOMPLETE_HOURS,
                detail=(
                    f"{_format_hours(worked)} / "
                    f"{_format_hours(rule.full_day_minutes)} "
                    f"on {prev_day.strftime('%d-%m-%Y')}"
                ),
            )
        )
    return out


def detect_prev_day_missing_punch(
    employees: list[Employee],
    prev_punches: list[Punch],
    prev_day: date | None,
    *,
    expected_emp_codes: frozenset[str] | None = None,
    roster_names: Mapping[str, str] = _EMPTY_NAMES,
    working_emp_codes_prev_day: frozenset[str] | None = None,
    wfh_weekdays: list[int] | None = None,
) -> list[ExceptionItem]:
    """Employees who had exactly one punch on the most recent prior working day.

    BioTime's `punch_state` is unreliable, so we don't try to distinguish
    "missing in" from "missing out" — a lone punch on a day means the
    timesheet for that day is incomplete, full stop. Surface it today so
    payroll/operations can chase the correction.

    `prev_day` is the calendar date we're reporting on (used in the detail
    line); `prev_punches` are that day's punches. Both come from
    PunchRepository.punches_for_previous_working_day.
    """
    if not prev_punches or prev_day is None:
        return []
    if wfh_weekdays and prev_day.weekday() in wfh_weekdays:
        return []
    counts: dict[str, int] = {}
    # First non-empty BioTime name we saw on prev_day — used as a fallback
    # when Odoo names aren't available (phase-1 mode).
    biotime_names: dict[str, str] = {}
    for p in prev_punches:
        if not p.emp_code:
            continue
        counts[p.emp_code] = counts.get(p.emp_code, 0) + 1
        if p.employee_name and p.emp_code not in biotime_names:
            biotime_names[p.emp_code] = p.employee_name

    lookup = _emp_lookup(employees)
    effective_roster = expected_emp_codes
    if effective_roster is not None and working_emp_codes_prev_day is not None:
        effective_roster = effective_roster & working_emp_codes_prev_day
    out: list[ExceptionItem] = []
    for code in _filter_roster(counts.keys(), effective_roster):
        if (
            effective_roster is None
            and working_emp_codes_prev_day is not None
            and code not in working_emp_codes_prev_day
        ):
            continue
        if counts[code] != 1:
            continue
        emp = lookup.get(code)
        # Synthesize a fallback Employee from BioTime name if today's
        # punch-derived list doesn't have one (employee was on prev_day
        # only, not today).
        if emp is None and code in biotime_names:
            emp = Employee(
                emp_code=code, name=biotime_names[code], department="", active=True
            )
        name = _resolve_name(code, roster_names, emp)
        if name is None:
            continue
        out.append(
            ExceptionItem(
                emp_code=code,
                name=name,
                department=(emp.department if emp else "") or "",
                severity=ExceptionSeverity.MEDIUM,
                tag=ExceptionTag.MISSING_PUNCH,
                # DD-MM-YYYY per Prezlab convention.
                detail=f"Missing punch on {prev_day.strftime('%d-%m-%Y')}",
            )
        )
    return out
