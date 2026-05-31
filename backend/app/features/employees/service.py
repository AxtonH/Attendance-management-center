"""Employees feature: pure service functions."""

from datetime import date, datetime
from typing import Mapping

from app.shared import shift_rules
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
    rule: ShiftRule | None = None,
    now: datetime | None = None,
    working_emp_codes: frozenset[str] | None = None,
    on_leave_emp_codes: frozenset[str] | None = None,
    on_holiday_emp_codes: frozenset[str] | None = None,
) -> EmployeesTodayResponse:
    """One row per employee: first and last punch of the day.

    punch_out is None when there's only one punch (or every punch is at the
    same minute). This avoids showing a meaningless 'out at same time as in'.

    When `expected_emp_codes` is provided (Odoo roster), only those employees
    appear in the table — keeps this view consistent with the Present/Absent
    tile counts. Names come from `roster_names` (Odoo) when available, then
    from the punch-derived `employees` list (BioTime) as fallback.

    When `rule` and `now` are also provided, roster employees who were
    expected today but never punched are appended as absent rows (null
    punches, `absent=True`) — same conditions as the dashboard's absent
    detector: not a WFH weekday, past the absent cutoff, and (if
    `working_emp_codes` is given) on the schedule for `day`. The weekly
    builder doesn't pass these, so per-day punch grouping is unaffected.

    `on_leave_emp_codes` / `on_holiday_emp_codes` (when given) are the sets
    of emp_codes excused today — by an approved full-day Time Off entry, or
    by a company-wide public holiday respectively. Such an employee, if
    they'd otherwise be absent, is emitted as an excused row instead
    (`on_holiday=True` or `on_leave=True`, with `absent=False`). Holiday
    wins over leave when both apply.
    """
    on_leave = on_leave_emp_codes or frozenset()
    on_holiday = on_holiday_emp_codes or frozenset()
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
        # Leave / holiday always wins the worked-time column, even when the
        # employee punched (e.g. came in briefly on their day off). We keep
        # the punch times visible but flag the row so the UI shows the
        # On-leave / Holiday pill instead of a worked-time duration. Holiday
        # wins over leave when both apply.
        is_on_holiday = code in on_holiday
        is_on_leave = (not is_on_holiday) and code in on_leave
        rows.append(
            EmployeeDay(
                emp_code=code,
                name=name,
                punch_in=first,
                punch_out=punch_out,
                worked_minutes=worked_minutes,
                on_leave=is_on_leave,
                on_holiday=is_on_holiday,
            )
        )

    # Append absent rows — roster employees expected today who never
    # punched. Gated on the same conditions as the dashboard's
    # `detect_absent` so the two views never disagree: we need a roster,
    # a rule + clock to evaluate the cutoff, it can't be a WFH weekday,
    # and `now` must be past the absent cutoff. Skipped entirely when the
    # absence inputs aren't supplied (e.g. the weekly per-day path).
    if (
        expected_emp_codes is not None
        and rule is not None
        and now is not None
        and day.weekday() not in rule.wfh_weekdays
        and now >= shift_rules.absent_cutoff_dt(rule, day)
    ):
        roster = expected_emp_codes
        if working_emp_codes is not None:
            roster = roster & working_emp_codes
        punched = set(by_code.keys())
        for code in roster - punched:
            name = roster_names.get(code)
            if not name:
                # Roster code with no Odoo name → not a real employee,
                # same drop rule the present-row branch applies.
                continue
            # A public holiday or approved full-day Time Off excuses the
            # absence: emit an excused row so it reads as planned, not
            # missing. Holiday wins over leave when both apply.
            is_on_holiday = code in on_holiday
            is_on_leave = (not is_on_holiday) and code in on_leave
            rows.append(
                EmployeeDay(
                    emp_code=code,
                    name=name,
                    punch_in=None,
                    punch_out=None,
                    worked_minutes=None,
                    absent=not (is_on_holiday or is_on_leave),
                    on_leave=is_on_leave,
                    on_holiday=is_on_holiday,
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
    now: datetime | None = None,
    working_emp_codes_by_day: Mapping[date, frozenset[str] | None] | None = None,
    on_leave_emp_codes_by_day: Mapping[date, frozenset[str]] | None = None,
    on_holiday_emp_codes_by_day: Mapping[date, frozenset[str]] | None = None,
) -> EmployeesWeekResponse:
    """One parent row per employee with a child row per day in range.

    Composition over `build_employees_today`: we call it once per day in
    the range, then group the resulting `EmployeeDay`s by emp_code. That
    means the name-resolution, roster-filter, and absent-detection rules
    stay identical between Daily and Weekly views — no logic drift.

    When `rule` and `now` are provided alongside a roster, the per-day
    call also emits absent rows (scheduled in-office days an employee
    missed), which become `absent=True` child days here. Employees who
    never punched but were scheduled on at least one in-office day in the
    range still get a parent row — all of whose child days are absent. A
    day only counts as absent once it's settled (past that day's absent
    cutoff), so the current day pre-cutoff never shows phantom absences.

    Without `rule`/`now` (phase-1, or the monthly/range endpoints that
    don't pass them) the old behavior holds: only punched days appear and
    fully-absent employees are omitted.

    `on_leave_emp_codes_by_day` / `on_holiday_emp_codes_by_day` map each day
    to the emp_codes excused that day (Time Off / public holiday); those
    days surface as `on_leave=True` / `on_holiday=True` children (and the
    person gets a parent row even if excused the whole range). Holiday wins
    over leave on a day where both apply.

    `days_worked` and `total_worked_minutes` count worked days only —
    absent, on-leave, and on-holiday child days never contribute.

    Per-employee `expected_days` counts in-office workdays for the week:
    days the schedule covers them MINUS WFH days (Prezlab's Thursday).
    When `rule` and `working_emp_codes_by_day` are not provided the
    expecteds default to 0 — phase-1 behavior, no schedule data.
    """
    absence_enabled = (
        expected_emp_codes is not None and rule is not None and now is not None
    )

    # emp_code → {name, days: [EmployeeWeekDay], total_minutes, days_worked}
    by_code: dict[str, dict] = {}

    for day in days:
        day_punches = punches_by_day.get(day, [])
        # When absence detection is off we keep the original fast-path:
        # skip days nobody punched. With it on we must still visit empty
        # days so a company-wide or fully-absent miss surfaces.
        if not day_punches and not absence_enabled:
            continue
        per_day = build_employees_today(
            employees,
            day_punches,
            day,
            expected_emp_codes=expected_emp_codes,
            roster_names=roster_names,
            rule=rule if absence_enabled else None,
            now=now if absence_enabled else None,
            working_emp_codes=(
                working_emp_codes_by_day.get(day)
                if absence_enabled and working_emp_codes_by_day is not None
                else None
            ),
            on_leave_emp_codes=(
                on_leave_emp_codes_by_day.get(day)
                if absence_enabled and on_leave_emp_codes_by_day is not None
                else None
            ),
            on_holiday_emp_codes=(
                on_holiday_emp_codes_by_day.get(day)
                if absence_enabled and on_holiday_emp_codes_by_day is not None
                else None
            ),
        )
        for row in per_day.rows:
            entry = by_code.setdefault(
                row.emp_code,
                {"name": row.name, "days": [], "total_minutes": 0, "days_worked": 0},
            )
            entry["days"].append(
                EmployeeWeekDay(
                    date=day.isoformat(),
                    punch_in=row.punch_in,
                    punch_out=row.punch_out,
                    worked_minutes=row.worked_minutes,
                    absent=row.absent,
                    on_leave=row.on_leave,
                    on_holiday=row.on_holiday,
                )
            )
            # A worked day is one the employee was genuinely working — not
            # absent, on leave, or on holiday. A leave/holiday day can still
            # carry a punch (they popped in briefly), so gate BOTH the
            # day count and the worked-minutes sum on the same condition;
            # excused minutes must not inflate the weekly total.
            is_worked_day = (
                not row.absent and not row.on_leave and not row.on_holiday
            )
            if is_worked_day:
                entry["days_worked"] += 1
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
                days_worked=entry["days_worked"],
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
