"""Dashboard feature: pure service functions.

Orchestrates: employees + punches + shift rule → response models.
No I/O — infrastructure fetches the inputs, API ships the outputs.

Exception detection itself lives in `dashboard.exceptions` (one pure
function per exception type); this module composes them, applies ordering,
and handles filtering.
"""

from datetime import date, datetime, timedelta
from typing import Mapping

from app.shared import shift_rules
from app.shared.models import AttendanceStatus, Employee, Punch, ShiftRule

from app.features.dashboard.exceptions import (
    detect_absent,
    detect_late,
    detect_prev_day_incomplete_hours,
    detect_prev_day_missing_punch,
)
from app.features.dashboard.models import (
    ArrivalBucket,
    ArrivalsResponse,
    DashboardResponse,
    DepartmentRollup,
    DepartmentsResponse,
    ExceptionItem,
    ExceptionsResponse,
    ExceptionTag,
    OverviewResponse,
)


def _first_punch_per_employee(punches: list[Punch]) -> dict[str, datetime]:
    """Earliest punch_time per emp_code. Ignores rows without emp_code."""
    earliest: dict[str, datetime] = {}
    for p in punches:
        if not p.emp_code:
            continue
        prev = earliest.get(p.emp_code)
        if prev is None or p.punch_time < prev:
            earliest[p.emp_code] = p.punch_time
    return earliest


def build_overview(
    employees: list[Employee],
    punches: list[Punch],
    rule: ShiftRule,
    day: date,
    now: datetime,
    *,
    expected_emp_codes: frozenset[str] | None = None,
    working_emp_codes: frozenset[str] | None = None,
) -> OverviewResponse:
    """Semantics:

    With Odoo roster (`expected_emp_codes` provided):
    - The roster IS the universe. Present + Absent = len(expected_today).
    - When `working_emp_codes` is also provided, the universe narrows to
      employees whose schedule covers `day` (Mon=0..Sun=6) — so weekend
      tiles aren't padded with everybody's "absences".
    - Present = roster_today ∩ punchers.
    - Absent  = roster_today − punchers.
    - Punches from emp_codes outside the roster (visitors, ex-employees
      still in BioTime, test cards) are ignored.

    Without Odoo roster (phase-1 fallback):
    - Present = everyone who punched (roster is unknown, so we can't filter).
    - Absent  = None → tile renders "—".

    WFH days (`rule.wfh_weekdays`): no one is expected in the office, so
    Absent = 0 and Late = 0. Present still reflects whoever did punch.
    """
    is_wfh = day.weekday() in rule.wfh_weekdays
    first_punches = _first_punch_per_employee(punches)
    punched_codes = set(first_punches.keys())

    if expected_emp_codes is not None:
        roster_codes = expected_emp_codes
        if working_emp_codes is not None:
            roster_codes = roster_codes & working_emp_codes
        # WFH: nobody is "expected in office", so Absent collapses to 0.
        absent: int | None = 0 if is_wfh else len(roster_codes - punched_codes)
    else:
        # Phase-1 universe = whoever appears in the active punch-derived list.
        roster_codes = frozenset(e.emp_code for e in employees if e.active)
        absent = None

    present = 0
    late = 0
    for code in roster_codes & punched_codes:
        present += 1
        # Don't count Late on WFH days — those punches are voluntary
        # office time, not late attendance for a tracked shift.
        if is_wfh:
            continue
        first_punch = first_punches[code]
        if shift_rules.classify(first_punch, rule, day, now=now) == AttendanceStatus.LATE:
            late += 1

    return OverviewResponse(
        date=day.isoformat(),
        present=present,
        late=late,
        absent=absent,
    )


_TAG_ORDER: dict[ExceptionTag, int] = {
    ExceptionTag.ABSENT: 0,
    ExceptionTag.MISSING_PUNCH: 1,
    ExceptionTag.INCOMPLETE_HOURS: 2,
    ExceptionTag.LATE: 3,
    ExceptionTag.PATTERN: 4,
    ExceptionTag.REVIEW: 5,
}

# Filter chip values the panel UI sends, mapped to the tags they include.
# "all" returns everything; other values are exact tag matches.
_FILTER_TAGS: dict[str, set[ExceptionTag]] = {
    "all": set(_TAG_ORDER),
    "late": {ExceptionTag.LATE},
    "absent": {ExceptionTag.ABSENT},
    "missing_punch": {ExceptionTag.MISSING_PUNCH},
    "incomplete_hours": {ExceptionTag.INCOMPLETE_HOURS},
    "review": {ExceptionTag.REVIEW},
}


_EMPTY_NAMES: Mapping[str, str] = {}


def build_exceptions(
    employees: list[Employee],
    punches: list[Punch],
    rule: ShiftRule,
    day: date,
    now: datetime,
    *,
    filter_type: str = "all",
    expected_emp_codes: frozenset[str] | None = None,
    roster_names: Mapping[str, str] = _EMPTY_NAMES,
    working_emp_codes: frozenset[str] | None = None,
    working_emp_codes_prev_day: frozenset[str] | None = None,
    prev_working_day: date | None = None,
    prev_working_day_punches: list[Punch] | None = None,
) -> ExceptionsResponse:
    """Compose all detected exceptions into a single sorted list.

    Detectors live in `dashboard.exceptions`; this function only orchestrates:
      1. Run each detector with the data it needs.
      2. Concatenate, then sort by (tag priority, late-minutes desc, name).
      3. Apply the filter chip selection.

    When `expected_emp_codes` is None we have no roster → absent detector is a
    no-op and late detection falls back to whoever punched.

    `prev_working_day_punches` is the last working day's punches (one row per
    raw event) plus the date they fell on. When omitted, missing-punch
    detection is skipped — useful for the panel-only `/exceptions` endpoint
    if a caller doesn't want the extra Supabase round-trip.
    """
    first_punches = _first_punch_per_employee(punches)

    late_pairs = detect_late(
        employees, first_punches, rule, day, now,
        expected_emp_codes=expected_emp_codes,
        roster_names=roster_names,
    )
    absent_items = detect_absent(
        employees, first_punches, rule, day, now,
        expected_emp_codes=expected_emp_codes,
        roster_names=roster_names,
        working_emp_codes=working_emp_codes,
    )
    missing_items = detect_prev_day_missing_punch(
        employees,
        prev_working_day_punches or [],
        prev_working_day,
        expected_emp_codes=expected_emp_codes,
        roster_names=roster_names,
        working_emp_codes_prev_day=working_emp_codes_prev_day,
        wfh_weekdays=rule.wfh_weekdays,
    )
    incomplete_items = detect_prev_day_incomplete_hours(
        employees,
        prev_working_day_punches or [],
        prev_working_day,
        rule,
        expected_emp_codes=expected_emp_codes,
        roster_names=roster_names,
        working_emp_codes_prev_day=working_emp_codes_prev_day,
    )

    minutes_by_code = {item.emp_code: mins for mins, item in late_pairs}
    all_items: list[ExceptionItem] = absent_items + missing_items + incomplete_items + [
        item for _, item in late_pairs
    ]

    def sort_key(item: ExceptionItem) -> tuple[int, int, str]:
        # Tag priority first; within Late, worst lateness first; name breaks ties.
        return (
            _TAG_ORDER.get(item.tag, 99),
            -minutes_by_code.get(item.emp_code, 0),
            item.name,
        )

    allowed = _FILTER_TAGS.get(filter_type, set())
    filtered = [item for item in all_items if item.tag in allowed]
    filtered.sort(key=sort_key)

    return ExceptionsResponse(
        date=day.isoformat(), total=len(filtered), items=filtered
    )


def build_departments_placeholder(day: date) -> DepartmentsResponse:
    """Phase 1 stand-in. Empty list = panel shows the 'Available with Odoo'
    placeholder via the frontend's `departments.length === 0` guard."""
    return DepartmentsResponse(date=day.isoformat(), departments=[])


# Sort by violation severity (worst first), tie-break by department name.
def _rollup_sort_key(r: DepartmentRollup) -> tuple[int, int, str]:
    # Negative for desc: more absences first, then more lates, then name asc.
    return (-r.absent, -r.late, r.name.lower())


def build_departments_rollup(
    punches: list[Punch],
    rule: ShiftRule,
    day: date,
    now: datetime,
    department_by_emp_code: Mapping[str, str],
    *,
    expected_emp_codes: frozenset[str] | None = None,
    working_emp_codes: frozenset[str] | None = None,
) -> DepartmentsResponse:
    """Group the Present/Late/Absent math by Odoo department.

    Same universe rules as `build_overview`: when an Odoo roster is set,
    the universe is `expected ∩ working_today`. WFH days collapse Absent
    and Late to 0 across all rows. Departments with zero expected employees
    are dropped from the response (the frontend never renders 0/0 rows).

    No I/O: department names come from the cached `department_by_emp_code`
    map. The rollup runs in one pass over (roster, punches), O(N).
    """
    if not department_by_emp_code or expected_emp_codes is None:
        return DepartmentsResponse(date=day.isoformat(), departments=[])

    is_wfh = day.weekday() in rule.wfh_weekdays
    universe = expected_emp_codes
    if working_emp_codes is not None:
        universe = universe & working_emp_codes

    first_punches = _first_punch_per_employee(punches)
    punched_codes = set(first_punches.keys())

    # dept_name → [expected, present, late, absent]
    buckets: dict[str, list[int]] = {}
    for code in universe:
        dept = department_by_emp_code.get(code) or "Unassigned"
        slot = buckets.setdefault(dept, [0, 0, 0, 0])
        slot[0] += 1  # expected
        if code in punched_codes:
            slot[1] += 1  # present
            if not is_wfh:
                first = first_punches[code]
                if (
                    shift_rules.classify(first, rule, day, now=now)
                    == AttendanceStatus.LATE
                ):
                    slot[2] += 1  # late
        elif not is_wfh:
            slot[3] += 1  # absent

    rows = [
        DepartmentRollup(
            name=name, expected=exp, present=pre, late=lt, absent=ab
        )
        for name, (exp, pre, lt, ab) in buckets.items()
        if exp > 0  # already guaranteed by the universe loop, kept defensively
    ]
    rows.sort(key=_rollup_sort_key)
    return DepartmentsResponse(date=day.isoformat(), departments=rows)


def _hhmm_to_dt(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m)


def _round_up_to_bucket(dt: datetime, bucket_minutes: int) -> datetime:
    """Round a datetime up to the next bucket boundary.

    e.g. 10:23 with 15-min buckets → 10:30. Already-on-boundary values are
    bumped to the next boundary so the bucket containing the punch is included.
    """
    minute = (dt.minute // bucket_minutes) * bucket_minutes
    floored = dt.replace(minute=minute, second=0, microsecond=0)
    return floored + timedelta(minutes=bucket_minutes)


def build_arrivals(
    punches: list[Punch],
    day: date,
    bucket_minutes: int = 30,
    window_start: str = "08:00",
    window_end: str | None = None,
    *,
    min_window_end: str = "10:30",
) -> ArrivalsResponse:
    """Bucket first-punch times into fixed windows for the histogram.

    When `window_end` is None, the end is computed from the data: the latest
    first-punch rounded up to the next bucket, but never earlier than
    `min_window_end`. That way a quiet morning still shows a familiar 07:30→
    10:30 window, and a day where someone arrives at 11:27 extends to 11:30.
    """
    first_punches = _first_punch_per_employee(punches)
    window_start_dt = _hhmm_to_dt(day, window_start)
    min_end_dt = _hhmm_to_dt(day, min_window_end)

    if window_end is not None:
        window_end_dt = _hhmm_to_dt(day, window_end)
    elif first_punches:
        latest = max(first_punches.values())
        window_end_dt = max(min_end_dt, _round_up_to_bucket(latest, bucket_minutes))
    else:
        window_end_dt = min_end_dt

    buckets: list[ArrivalBucket] = []
    cursor = window_start_dt
    while cursor < window_end_dt:
        next_cursor = cursor + timedelta(minutes=bucket_minutes)
        count = sum(1 for t in first_punches.values() if cursor <= t < next_cursor)
        buckets.append(ArrivalBucket(label=cursor.strftime("%H:%M"), count=count))
        cursor = next_cursor

    return ArrivalsResponse(date=day.isoformat(), bucket_minutes=bucket_minutes, buckets=buckets)


def build_dashboard(
    employees: list[Employee],
    punches: list[Punch],
    rule: ShiftRule,
    day: date,
    now: datetime,
    *,
    expected_emp_codes: frozenset[str] | None = None,
    roster_names: Mapping[str, str] = _EMPTY_NAMES,
    working_emp_codes: frozenset[str] | None = None,
    working_emp_codes_prev_day: frozenset[str] | None = None,
    department_by_emp_code: Mapping[str, str] | None = None,
    prev_working_day: date | None = None,
    prev_working_day_punches: list[Punch] | None = None,
    arrival_bucket_minutes: int = 15,
    arrival_window_start: str = "07:30",
) -> DashboardResponse:
    """One pass over the punches; everything the dashboard needs in one payload.

    `prev_working_day_punches` powers the missing-punch detector. The route
    layer fetches them in one extra Supabase round-trip (bounded backward
    scan) and threads them through here.

    Arrival histogram auto-extends past the latest first-punch — no hardcoded
    end time, so late arrivals always show up on the chart.
    """
    return DashboardResponse(
        date=day.isoformat(),
        overview=build_overview(
            employees,
            punches,
            rule,
            day,
            now,
            expected_emp_codes=expected_emp_codes,
            working_emp_codes=working_emp_codes,
        ),
        exceptions=build_exceptions(
            employees,
            punches,
            rule,
            day,
            now,
            expected_emp_codes=expected_emp_codes,
            roster_names=roster_names,
            working_emp_codes=working_emp_codes,
            working_emp_codes_prev_day=working_emp_codes_prev_day,
            prev_working_day=prev_working_day,
            prev_working_day_punches=prev_working_day_punches,
        ),
        arrivals=build_arrivals(
            punches,
            day,
            bucket_minutes=arrival_bucket_minutes,
            window_start=arrival_window_start,
        ),
        departments=(
            build_departments_rollup(
                punches,
                rule,
                day,
                now,
                department_by_emp_code,
                expected_emp_codes=expected_emp_codes,
                working_emp_codes=working_emp_codes,
            )
            if department_by_emp_code
            else build_departments_placeholder(day)
        ),
    )
