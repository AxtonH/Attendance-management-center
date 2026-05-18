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
    """Aggregate Present/Late/Absent across the week.

    - Present = distinct employees who showed up at least once in the week.
      One Prezlaber who came in 4 days still counts as 1.
    - Late and Absent = person-day sums (one person late on 3 days = 3).
    """
    present_codes: set[str] = set()
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

        # Present: accumulate distinct codes across the whole week.
        present_codes |= roster & punched

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
        present=len(present_codes),
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
    """Per-department weekly rollup.

    - `expected` = distinct people scheduled at least one day this week.
    - `present`  = distinct people who showed up at least one day this week.
    - `late` / `absent` = person-day sums (one person late twice = 2).

    The "X / Y" tile reading is now "distinct people who showed up out of
    distinct people who work in this department this week" — not a sum of
    per-day scheduled slots. Sort: most absences first (person-days),
    then most lates, then name.
    """
    if not department_by_emp_code or expected_emp_codes is None:
        return DepartmentsResponse(date=days[0].isoformat(), departments=[])

    # Per-department state. Sets get unioned across days, ints summed.
    expected_people: dict[str, set[str]] = defaultdict(set)
    present_people: dict[str, set[str]] = defaultdict(set)
    late_pdays: dict[str, int] = defaultdict(int)
    absent_pdays: dict[str, int] = defaultdict(int)

    def dept_of(code: str) -> str:
        return department_by_emp_code.get(code) or "Unassigned"

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
            dept = dept_of(code)
            expected_people[dept].add(code)
            if code in punched:
                present_people[dept].add(code)
                if not is_wfh:
                    first = first_punches[code]
                    if (
                        shift_rules.classify(first, rule, day, now=now)
                        == AttendanceStatus.LATE
                    ):
                        late_pdays[dept] += 1
            elif not is_wfh and now >= shift_rules.grace_end_dt(rule, day):
                absent_pdays[dept] += 1

    rows = [
        DepartmentRollup(
            name=name,
            expected=len(expected_people[name]),
            present=len(present_people[name]),
            late=late_pdays[name],
            absent=absent_pdays[name],
        )
        for name in expected_people
        if expected_people[name]
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
    show_day_chips: bool = True,
) -> ExceptionsResponse:
    """Run every per-day detector across the range, then group by (tag, emp_code).

    Despite the "weekly" name, this composes across any day range — the
    monthly view reuses it with ~30 days.

    Each grouped row normally carries a `days` list of short weekday
    labels ("Mon", "Wed"). For longer ranges (monthly) the caller sets
    `show_day_chips=False`, which omits the chips and instead suffixes
    the detail line with "across N days" so the row stays readable.

    Missing-punch and incomplete-hours detectors look at the *prior*
    working day for each day in the range. Days falling outside the
    range are skipped so chip labels can't ambiguously refer to days
    outside the rendered window.
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
        # Prev-day detectors look at *yesterday's* timesheet. In weekly
        # view we report under the actual broken day (so chips match the
        # data), and we only fire when that day is inside the week being
        # rendered — otherwise the chip "Sat" would ambiguously read as
        # this week's Saturday when it actually means last week's. The
        # flag will surface in the previous week's view instead.
        prev_day = day - timedelta(days=1)
        if prev_day >= days[0]:
            prev_punches = punches_by_day.get(prev_day, [])
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
                prev_day,
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
                prev_day,
            )

    allowed = _FILTER_TAGS.get(filter_type, set())
    # Build a list of (item, occurrence_count) so the secondary sort key
    # (occurrences desc) survives even when `days` is omitted (monthly).
    items_with_n: list[tuple[ExceptionItem, int]] = []
    for (tag, emp_code), entry in grouped.items():
        if tag not in allowed:
            continue
        # Detail line: always summarized in weekly view. The daily
        # detectors append "today"/"on DD-MM-YYYY" text that reads wrong
        # here (the day chips on the row already convey *when*), so we
        # synthesize a clean weekly-tense string instead.
        n = len(entry["days"])
        label = _tag_label(tag).capitalize()
        if n == 1:
            detail = label
        elif show_day_chips:
            detail = f"{n}× {label.lower()}"
        else:
            # Monthly view: chips would explode visually, so encode the
            # day count into the detail instead.
            detail = f"{n}× {label.lower()} · across {n} days"
        unique_days = sorted(set(entry["days"]))
        items_with_n.append((
            ExceptionItem(
                emp_code=emp_code,
                name=entry["name"],
                department=entry["department"],
                severity=entry["severity"],
                tag=tag,
                detail=detail,
                days=(
                    [_WEEKDAY_LABELS[d.weekday()] for d in unique_days]
                    if show_day_chips
                    else None
                ),
            ),
            n,
        ))

    items_with_n.sort(key=lambda pair: (
        _TAG_ORDER.get(pair[0].tag, 99),
        -pair[1],
        pair[0].name.lower(),
    ))
    items = [it for it, _ in items_with_n]
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
    arrival_bucket_minutes: int = 15,
    arrival_window_start: str = "07:30",
    mode_label: str = "weekly",
    show_day_chips: bool = True,
) -> DashboardResponse:
    """Range-agnostic aggregator.

    `mode_label` and `show_day_chips` let the monthly route reuse this
    function unchanged: pass `mode_label="monthly"` and `show_day_chips=False`
    so the response advertises the right mode and the exception rows omit
    chips (the row count would otherwise explode for a 30-day range).
    """
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
        show_day_chips=show_day_chips,
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
        mode=mode_label,
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
