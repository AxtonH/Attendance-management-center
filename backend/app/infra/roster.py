"""Roster + departments + shift rule providers.

Phase 1: roster is *derived* from the punches themselves — every distinct
(emp_code, employee_name) we've seen counts as an employee. Departments are
unavailable until Odoo is wired in (phase 2).

Phase 2: `OdooRosterProvider` reads the enrolled-employee set + names +
working-day calendars from Odoo. That's the seam that lets `build_overview`
compute absent counts only for people who were actually expected that day.

The RosterProvider protocol is the shared shape. Phase-1 falls back to
"everyone is working every day" so domain code doesn't branch on which
provider is configured.
"""

from datetime import date
from pathlib import Path
from typing import Mapping, Protocol

import yaml

from app.infra.calendar_parser import PREZLAB_DEFAULT_DAYS
from app.infra.odoo_calendars import OdooCalendarRepository
from app.infra.odoo_employees import OdooEmployeeRepository
from app.infra.odoo_timesheets import OdooTimesheetRepository
from app.shared.models import Department, Employee, Punch, ShiftRule


def exclude_on_leave(
    working: frozenset[str] | None,
    on_leave: frozenset[str] | None,
) -> frozenset[str] | None:
    """Remove on-leave emp_codes from a day's working (in-office) set.

    People on approved full-day leave aren't expected in the office that
    day, so they drop out of the universe the dashboard uses for Present /
    Absent math and the department rollup — keeping the dashboard tab
    consistent with the Employees tab's "On leave" treatment.

    `working is None` is the phase-1 "no schedule info" sentinel; it's
    preserved as-is (we never fabricate a working set from leave data
    alone). `on_leave` None/empty is a no-op. Pure; no I/O.
    """
    if working is None or not on_leave:
        return working
    return working - on_leave


class RosterProvider(Protocol):
    def employees_from_punches(self, punches: list[Punch]) -> list[Employee]: ...
    def departments(self) -> list[Department]: ...
    def default_shift(self) -> ShiftRule: ...
    def expected_emp_codes(self) -> frozenset[str] | None: ...
    def display_names(self) -> Mapping[str, str]: ...
    def working_emp_codes_for(self, day: date) -> frozenset[str] | None: ...
    def department_by_emp_code(self) -> Mapping[str, str]: ...
    def on_leave_emp_codes_for_range(
        self, start: date, end: date
    ) -> Mapping[date, frozenset[str]] | None: ...


class PunchDerivedRosterProvider:
    """Phase 1 implementation: employees come from punches, departments empty.

    `employees_from_punches` is intentionally pure-ish: it takes the punches
    the caller already has, so we don't double-fetch. Phase 2's Odoo
    implementation will ignore the argument and return its own roster.
    """

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._shift: ShiftRule | None = None

    def reload(self) -> None:
        self._shift = None

    def employees_from_punches(self, punches: list[Punch]) -> list[Employee]:
        # Deduplicate by emp_code, keep the first non-empty name we see.
        names: dict[str, str] = {}
        for p in punches:
            if not p.emp_code:
                continue
            if p.emp_code not in names and p.employee_name:
                names[p.emp_code] = p.employee_name
            elif p.emp_code not in names:
                names[p.emp_code] = p.emp_code
        return [
            Employee(emp_code=code, name=name, department="", active=True)
            for code, name in sorted(names.items())
        ]

    def departments(self) -> list[Department]:
        return []

    def default_shift(self) -> ShiftRule:
        if self._shift is None:
            path = self._config_dir / "shift_rules.yaml"
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._shift = ShiftRule(**data["default_shift"])
        return self._shift

    def expected_emp_codes(self) -> frozenset[str] | None:
        # Phase 1: we don't know the full roster, so "absent" can't be
        # computed. Returning None tells the dashboard service to skip it.
        return None

    def display_names(self) -> Mapping[str, str]:
        # Phase 1: no authoritative name source. Empty means callers fall
        # back to whatever they have locally (e.g. BioTime's employee_name).
        return {}

    def working_emp_codes_for(self, day: date) -> frozenset[str] | None:
        # Phase 1: we don't have schedule data, so we can't filter by day.
        # Returning None signals "no schedule info — don't apply this filter".
        return None

    def department_by_emp_code(self) -> Mapping[str, str]:
        # Phase 1: no Odoo department data. Empty means the rollup builder
        # will skip the section (or render an empty list, per its choice).
        return {}

    def on_leave_emp_codes_for_range(
        self, start: date, end: date
    ) -> Mapping[date, frozenset[str]] | None:
        # Phase 1: no timesheet/leave data. None signals "no leave info —
        # don't reclassify any absence as on-leave".
        return None


class OdooRosterProvider:
    """Phase 2 implementation: roster comes from Odoo.

    Only the absent-count plumbing is wired up in this step. Department
    and shift overrides will be added in subsequent steps; `default_shift`
    still reads from the YAML config so existing behavior is preserved.

    `employees_from_punches` is intentionally still punch-derived for now —
    that keeps the existing exception/arrival panels unchanged. A later
    step will replace this with Odoo employee records (name, department).
    """

    def __init__(
        self,
        odoo_employees: OdooEmployeeRepository,
        odoo_calendars: OdooCalendarRepository,
        fallback: PunchDerivedRosterProvider,
        odoo_timesheets: OdooTimesheetRepository | None = None,
    ) -> None:
        self._odoo_employees = odoo_employees
        self._odoo_calendars = odoo_calendars
        self._odoo_timesheets = odoo_timesheets
        self._fallback = fallback

    def employees_from_punches(self, punches: list[Punch]) -> list[Employee]:
        return self._fallback.employees_from_punches(punches)

    def departments(self) -> list[Department]:
        return self._fallback.departments()

    def default_shift(self) -> ShiftRule:
        return self._fallback.default_shift()

    def expected_emp_codes(self) -> frozenset[str] | None:
        return self._odoo_employees.expected_emp_codes()

    def display_names(self) -> Mapping[str, str]:
        # Odoo is the source of truth for display names. Same cached payload
        # that powers expected_emp_codes — no extra round-trip.
        return self._odoo_employees.display_names()

    def department_by_emp_code(self) -> Mapping[str, str]:
        # Same cached payload that powers expected_emp_codes — no round-trip.
        return self._odoo_employees.departments()

    def working_emp_codes_for(self, day: date) -> frozenset[str]:
        """Employees whose schedule covers `day` (Mon=0..Sun=6).

        Composes two cached lookups:
          emp_code → calendar_id (from hr.employee)
          calendar_id → set of working weekdays (from resource.calendar*)

        Hot-path cost: one weekday lookup + per-employee O(1) set membership.
        Employees with no calendar fall back to Prezlab's standard Sun–Thu —
        the most common shape, and consistent with the "no surprises" rule.
        """
        weekday = day.weekday()
        emp_to_cal = self._odoo_employees.calendar_ids()
        working: set[str] = set()
        for code, cal_id in emp_to_cal.items():
            if cal_id is None:
                # No calendar configured → Prezlab default (Sun–Thu).
                days = PREZLAB_DEFAULT_DAYS
            else:
                days = self._odoo_calendars.working_days_for_calendar(cal_id)
            if weekday in days:
                working.add(code)
        return frozenset(working)

    def on_leave_emp_codes_for_range(
        self, start: date, end: date
    ) -> Mapping[date, frozenset[str]] | None:
        """Full-day leave per day in [start, end], keyed by emp_code.

        Composes the timesheet repo (raw leave lines) with the employee
        repo's id→code map (already cached) so leave lines resolve to our
        canonical emp_codes. Returns None when no timesheet repo is wired —
        callers then skip leave reclassification entirely.
        """
        if self._odoo_timesheets is None:
            return None
        return self._odoo_timesheets.on_leave_emp_codes_for_range(
            start, end, self._odoo_employees.emp_code_by_odoo_id()
        )
