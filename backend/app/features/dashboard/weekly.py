"""Weekly aggregation layer for the dashboard.

Composes the existing per-day functions over a 7-day range. Zero new domain
logic — late/absent/missing-punch/incomplete-hours rules and the WFH and
working-day filters all flow through unchanged. The only new concepts are:

  - Tile counts sum *person-days* (one person late three times = 3).
  - Arrival histogram averages each employee's first-punch time across the
    days they actually punched in, then buckets the mean.
  - Department rollups sum per-day buckets across the week.
  - Exceptions group by (tag, emp_code) with a `days` list of weekday
    labels so the panel can show small day chips.

All pure functions. No I/O. The route prepares the inputs (one Supabase
query covers the week; Odoo state is already cached) and hands them in.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Mapping

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
from app.features.dashboard.service import (
    _FILTER_TAGS,
    _TAG_ORDER,
    _first_punch_per_employee,
    _hhmm_to_dt,
    _round_up_to_bucket,
)
from app.shared import shift_rules
from app.shared.date_range import iter_days
from app.shared.models import AttendanceStatus, Employee, Punch, ShiftRule

_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------- Overview ----------


def build_weekly_overview(
    punches_by_day: Mapping[date, list[Punch]],
    rule: ShiftRule,
    days: list[date],
    now: datetime,
    *,
    expected_emp_codes: frozenset[str] | None = None,
    working_emp_codes_by_day: Mapping[date, frozenset[str] | None] | None = None,
) -> OverviewResponse:
    """Sum the per-day Present/Late/Absent counts across the week.

    Tile semantics = person-days. One employee late on three days
    contributes 3 to Late. Weekend days (off for everyone in the working
    set) and WFH days contribute 0 by construction — same gates as daily.
    """
    total_present = 0
    total_late = 0
    total_absent = 0

    for day in days:
        is_wfh = day.weekday() in rule.wfh_weekdays
        first_punches = _first_punch_per_employee(punches_by_day.get(day, []))
        punched = set(first_punches.keys())

        working = (
            working_emp_codes_by_day.get(day) if working_emp_codes_by_day else None
        )
        if expected_emp_codes is not None:
            roster = expected_emp_codes
            if working is not None:
                roster = roster & working
        else:
            roster = punched  # phase-1 fallback

        # Present: everyone in the day's roster who punched.
        day_present = len(roster & punched)
        total_present += day_present

        # Late and Absent both suppressed on WFH days and during the
        # grace window (no provisional flags before grace_end).
        if is_wfh or now < shift_rules.grace_end_dt(rule, day):
            continue
        # Late: count those whose first punch was past grace.
        for code in roster & punched:
            if (
                shift_rules.classify(first_punches[code], rule, day, now=now)
                == AttendanceStatus.LATE
            ):
                total_late += 1
        # Absent only counted when we have a real roster (Odoo).
        if expected_emp_codes is not None:
            total_absent += len(roster - punched)

    return OverviewResponse(
        date=days[0].isoformat(),
        present=total_present,
        late=total_late,
        absent=total_absent if expected_emp_codes is not None else None,
    )


# ---------- Department rollup ----------


def build_weekly_departments_rollup(
    punches_by_day: Mapping[date, list[Punch]],
    rule: ShiftRule,
    days: list[date],
    now: datetime,
    department_by_emp_code: Mapping[str, str],
    *,
    expected_emp_codes: frozenset[str] | None = None,
    working_emp_codes_by_day: Mapping[date, frozenset[str] | None] | None = None,
) -> DepartmentsResponse:
    """Per-department person-day totals across the week.

    Same per-day math as `build_departments_rollup`, summed. Empty
    departments (zero expected across the whole week) are dropped.
    Sort: worst-first — most absent, then most late, then name.
    """
    if not department_by_emp_code or expected_emp_codes is None:
        return DepartmentsResponse(date=days[0].isoformat(), departments=[])

    # dept_name → [expected, present, late, absent]
    buckets: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])

    for day in days:
        is_wfh = day.weekday() in rule.wfh_weekdays
        first_punches = _first_punch_per_employee(punches_by_day.get(day, []))
        punched = set(first_punches.keys())

        working = (
            working_emp_codes_by_day.get(day) if working_emp_codes_by_day else None
        )
        roster = expected_emp_codes
        if working is not None:
            roster = roster & working

        for code in roster:
            dept = department_by_emp_code.get(code) or "Unassigned"
            slot = buckets[dept]
            slot[0] += 1  # expected (person-day)
            if code in punched:
                slot[1] += 1
                if not is_wfh:
                    first = first_punches[code]
                    if (
                        shift_rules.classify(first, rule, day, now=now)
                        == AttendanceStatus.LATE
                    ):
                        slot[2] += 1
            elif not is_wfh and now >= shift_rules.grace_end_dt(rule, day):
                slot[3] += 1

    rows = [
        DepartmentRollup(
            name=name, expected=exp, present=pre, late=lt, absent=ab
        )
        for name, (exp, pre, lt, ab) in buckets.items()
        if exp > 0
    ]
    rows.sort(key=lambda r: (-r.absent, -r.late, r.name.lower()))
    return DepartmentsResponse(date=days[0].isoformat(), departments=rows)


# ---------- Arrivals histogram ----------


def build_weekly_arrivals(
    punches_by_day: Mapping[date, list[Punch]],
    days: list[date],
    *,
    bucket_minutes: int = 15,
    window_start: str = "07:30",
    min_window_end: str = "10:30",
    expected_emp_codes: frozenset[str] | None = None,
) -> ArrivalsResponse:
    """Bucket each employee's *average* first-punch time across the week.

    For each employee, take their first punch on each day they punched in.
    Average those times-of-day. Bucket the result. Days they didn't punch
    don't count toward the average — the bucket reflects "when does Omar
    typically arrive when he does."

    All times are reduced to minutes-since-midnight before averaging so
    we don't have to think about calendar arithmetic.
    """
    # emp_code → list of "minutes since midnight" for each day they punched
    minutes_by_emp: dict[str, list[int]] = defaultdict(list)
    for day in days:
        firsts = _first_punch_per_employee(punches_by_day.get(day, []))
        for code, dt in firsts.items():
            if expected_emp_codes is not None and code not in expected_emp_codes:
                continue
            minutes_by_emp[code].append(dt.hour * 60 + dt.minute)

    # Average per employee. Then bucket all averages.
    averages_minutes: list[int] = [
        round(sum(times) / len(times)) for times in minutes_by_emp.values()
    ]

    # Anchor the histogram axis to `days[0]` for label rendering only;
    # the values inside are pure time-of-day so the date doesn't matter.
    anchor = days[0]
    window_start_dt = _hhmm_to_dt(anchor, window_start)
    min_end_dt = _hhmm_to_dt(anchor, min_window_end)

    if averages_minutes:
        latest_minute = max(averages_minutes)
        latest_dt = datetime.combine(anchor, datetime.min.time()) + timedelta(
            minutes=latest_minute
        )
        window_end_dt = max(min_end_dt, _round_up_to_bucket(latest_dt, bucket_minutes))
    else:
        window_end_dt = min_end_dt

    buckets: list[ArrivalBucket] = []
    cursor = window_start_dt
    while cursor < window_end_dt:
        cursor_min = cursor.hour * 60 + cursor.minute
        next_cursor = cursor + timedelta(minutes=bucket_minutes)
        next_min = next_cursor.hour * 60 + next_cursor.minute
        count = sum(1 for m in averages_minutes if cursor_min <= m < next_min)
        buckets.append(ArrivalBucket(label=cursor.strftime("%H:%M"), count=count))
        cursor = next_cursor

    return ArrivalsResponse(
        date=anchor.isoformat(), bucket_minutes=bucket_minutes, buckets=buckets
    )


# ---------- Exceptions ----------


def build_weekly_exceptions(
    employees: list[Employee],
    punches_by_day: Mapping[date, list[Punch]],
    rule: ShiftRule,
    days: list[date],
    now: datetime,
    *,
    filter_type: str = "all",
    expected_emp_codes: frozenset[str] | None = None,
    roster_names: Mapping[str, str] | None = None,
    working_emp_codes_by_day: Mapping[date, frozenset[str] | None] | None = None,
    prev_day_before_range: date | None = None,
    prev_day_before_range_punches: list[Punch] | None = None,
) -> ExceptionsResponse:
    """Run every per-day detector across the week, then group by (tag, emp_code).

    Each grouped row carries a `days` list of short weekday labels
    ("Mon", "Wed"). Order within tag is by number of occurrences desc
    (more frequent issues first), then by name.

    Missing-punch and incomplete-hours detectors look at the *prior*
    working day for each day in the range. For day 0 of the range (the
    Sunday), the route passes the punches from the day before that so
    the boundary works correctly.
    """
    roster_names = roster_names or {}
    # (tag, emp_code) → {"name": ..., "department": ..., "severity": ...,
    #                    "details": [str, ...], "days": [date, ...]}
    grouped: dict[tuple[ExceptionTag, str], dict] = {}

    def absorb(items: list[ExceptionItem], day: date) -> None:
        for item in items:
            key = (item.tag, item.emp_code)
            entry = grouped.get(key)
            if entry is None:
                grouped[key] = {
                    "name": item.name,
                    "department": item.department,
                    "severity": item.severity,
                    "details": [item.detail],
                    "days": [day],
                }
            else:
                entry["details"].append(item.detail)
                entry["days"].append(day)
                # Prefer the highest severity seen (HIGH > MEDIUM > LOW).
                if _severity_rank(item.severity) > _severity_rank(entry["severity"]):
                    entry["severity"] = item.severity

    for day in days:
        first_punches = _first_punch_per_employee(punches_by_day.get(day, []))
        working_today = (
            working_emp_codes_by_day.get(day) if working_emp_codes_by_day else None
        )

        absorb(
            [
                item
                for _, item in detect_late(
                    employees,
                    first_punches,
                    rule,
                    day,
                    now,
                    expected_emp_codes=expected_emp_codes,
                    roster_names=roster_names,
                )
            ],
            day,
        )
        absorb(
            detect_absent(
                employees,
                first_punches,
                rule,
                day,
                now,
                expected_emp_codes=expected_emp_codes,
                roster_names=roster_names,
                working_emp_codes=working_today,
            ),
            day,
        )
        # Prev-day-style detectors need yesterday's punches. For day 0 of
        # the range that's prev_day_before_range_punches; for later days
        # it's the punches we already have for day - 1.
        prev_day = day - timedelta(days=1)
        if prev_day in punches_by_day:
            prev_punches = punches_by_day[prev_day]
        elif prev_day_before_range is not None and prev_day == prev_day_before_range:
            prev_punches = prev_day_before_range_punches or []
        else:
            prev_punches = []
        working_prev = (
            working_emp_codes_by_day.get(prev_day)
            if working_emp_codes_by_day
            else None
        )
        absorb(
            detect_prev_day_missing_punch(
                employees,
                prev_punches,
                prev_day,
                expected_emp_codes=expected_emp_codes,
                roster_names=roster_names,
                working_emp_codes_prev_day=working_prev,
                wfh_weekdays=rule.wfh_weekdays,
            ),
            # Report under the *day we noticed*, not the day with the bad
            # timesheet. So the chip shows the day a manager would chase it.
            day,
        )
        absorb(
            detect_prev_day_incomplete_hours(
                employees,
                prev_punches,
                prev_day,
                rule,
                expected_emp_codes=expected_emp_codes,
                roster_names=roster_names,
                working_emp_codes_prev_day=working_prev,
            ),
            day,
        )

    allowed = _FILTER_TAGS.get(filter_type, set())
    items: list[ExceptionItem] = []
    for (tag, emp_code), entry in grouped.items():
        if tag not in allowed:
            continue
        # Detail line: when an employee was late multiple times, surface
        # the count rather than concatenating per-day strings (which would
        # quickly become noise).
        n = len(entry["days"])
        detail = entry["details"][0] if n == 1 else f"{n}× {_tag_label(tag)}"
        items.append(
            ExceptionItem(
                emp_code=emp_code,
                name=entry["name"],
                department=entry["department"],
                severity=entry["severity"],
                tag=tag,
                detail=detail,
                days=[_WEEKDAY_LABELS[d.weekday()] for d in sorted(set(entry["days"]))],
            )
        )

    items.sort(key=lambda it: (
        _TAG_ORDER.get(it.tag, 99),
        -(len(it.days) if it.days else 0),
        it.name.lower(),
    ))
    return ExceptionsResponse(
        date=days[0].isoformat(), total=len(items), items=items
    )


# ---------- Aggregate (single-call) ----------


def build_weekly_dashboard(
    employees: list[Employee],
    punches_by_day: Mapping[date, list[Punch]],
    rule: ShiftRule,
    days: list[date],
    now: datetime,
    *,
    expected_emp_codes: frozenset[str] | None = None,
    roster_names: Mapping[str, str] | None = None,
    department_by_emp_code: Mapping[str, str] | None = None,
    working_emp_codes_by_day: Mapping[date, frozenset[str] | None] | None = None,
    prev_day_before_range: date | None = None,
    prev_day_before_range_punches: list[Punch] | None = None,
    arrival_bucket_minutes: int = 15,
    arrival_window_start: str = "07:30",
) -> DashboardResponse:
    overview = build_weekly_overview(
        punches_by_day, rule, days, now,
        expected_emp_codes=expected_emp_codes,
        working_emp_codes_by_day=working_emp_codes_by_day,
    )
    exceptions = build_weekly_exceptions(
        employees, punches_by_day, rule, days, now,
        expected_emp_codes=expected_emp_codes,
        roster_names=roster_names,
        working_emp_codes_by_day=working_emp_codes_by_day,
        prev_day_before_range=prev_day_before_range,
        prev_day_before_range_punches=prev_day_before_range_punches,
    )
    arrivals = build_weekly_arrivals(
        punches_by_day, days,
        bucket_minutes=arrival_bucket_minutes,
        window_start=arrival_window_start,
        expected_emp_codes=expected_emp_codes,
    )
    if department_by_emp_code:
        departments = build_weekly_departments_rollup(
            punches_by_day, rule, days, now, department_by_emp_code,
            expected_emp_codes=expected_emp_codes,
            working_emp_codes_by_day=working_emp_codes_by_day,
        )
    else:
        departments = DepartmentsResponse(date=days[0].isoformat(), departments=[])

    anchor = days[0]
    return DashboardResponse(
        date=anchor.isoformat(),
        mode="weekly",
        range_start=days[0].isoformat(),
        range_end=days[-1].isoformat(),
        overview=overview,
        exceptions=exceptions,
        arrivals=arrivals,
        departments=departments,
    )


# ---------- Small helpers ----------


def _severity_rank(s) -> int:
    # HIGH > MEDIUM > LOW so we keep the worst severity per (tag, employee).
    return {"high": 3, "medium": 2, "low": 1}.get(str(s.value), 0)


def _tag_label(tag: ExceptionTag) -> str:
    return {
        ExceptionTag.LATE: "late",
        ExceptionTag.ABSENT: "absent",
        ExceptionTag.MISSING_PUNCH: "missing punch",
        ExceptionTag.INCOMPLETE_HOURS: "incomplete day",
        ExceptionTag.PATTERN: "pattern",
        ExceptionTag.REVIEW: "review",
    }.get(tag, str(tag.value))
