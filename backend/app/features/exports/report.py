"""Exports feature: pure functions that shape employee attendance into a
renderer-agnostic report.

The report has two levels, mirroring the P&C reference workbook:

  - a *summary* (headline stats for the whole period + a one-row-per-employee
    overview table), and
  - one *section* per employee (their own stat block + a complete day-by-day
    calendar for the period, including days off / WFH days / upcoming days).

Both renderers (Excel: one sheet per section; PDF: one page per section)
consume `AttendanceReport` — format-specific code never touches attendance
logic, and column/label changes happen in exactly one place.

Built from the same `EmployeesWeekResponse` the Employees pages render, so
screen and file always agree. Fields the reference tracks but we don't yet
(position, pool, line manager, per-employee shift, missing *sign-ins*) are
intentionally absent — see the NOTE at the bottom of this docstring.

NOTE — reference fields not yet tracked by this system:
  - Position / Pool / Line manager: not in the Odoo payload we mirror.
  - Days WFH per employee: phase-1 uses the org-wide `wfh_weekdays` rule.
  - Missing sign-ins: punches are collapsed to first/last per day, so a
    missing *first* punch is indistinguishable from a normal arrival.
When those land (phase 3 Odoo work), extend `EmployeeSection` here and both
renderers pick them up automatically.

No I/O. No datetime.now(). Everything needed comes in as arguments.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from app.features.employees.models import EmployeesWeekResponse, EmployeeWeekDay
from app.shared import shift_rules
from app.shared.models import ShiftRule

# Day statuses. Present/Late/Absent/On leave/Holiday mirror the on-screen
# pills; WFH / Day off / Upcoming fill the calendar gaps the screen doesn't
# show (the reference workbook lists every day in the period).
STATUS_PRESENT = "Present"
STATUS_LATE = "Late"
STATUS_ABSENT = "Absent"
STATUS_ON_LEAVE = "On leave"
STATUS_HOLIDAY = "Holiday"
STATUS_WFH = "WFH"
STATUS_DAY_OFF = "Day off"
STATUS_UPCOMING = "—"  # day hasn't happened yet (or today, pre-cutoff)

_DASH = "—"


@dataclass(frozen=True)
class DayLine:
    """One calendar day on an employee's sheet/page."""

    date: str  # "01-06-2026" (DD-MM-YYYY per convention)
    weekday: str  # "Mon"
    status: str  # one of the STATUS_* constants
    check_in: str  # "09:05" or "—"
    check_out: str  # "17:30" or "—"
    worked: str  # "8h 25m" or "—"
    late_by: str  # "23m" when late, else ""


@dataclass(frozen=True)
class EmployeeSection:
    """One employee's full report: stat block + day-by-day calendar.

    `days_expected` counts *settled* scheduled in-office days (attended +
    absent) — excused days (leave/holiday) and upcoming days don't count,
    so `attendance_pct` is always attended / expected.
    """

    emp_code: str
    name: str
    department: str
    days_expected: int
    days_attended: int  # includes late days
    days_late: int
    days_absent: int
    days_on_leave: int
    days_holiday: int
    missing_signouts: int  # attended days with a first punch but no last
    avg_arrival: str  # "09:12" or "—"
    total_worked: str  # "142h 20m"
    avg_worked: str  # per attended day, "7h 06m" or "—"
    attendance_pct: str  # "90%" or "—"
    days: list[DayLine]


@dataclass(frozen=True)
class ReportStat:
    """One headline stat on the summary sheet/page."""

    label: str
    value: str
    detail: str = ""


@dataclass(frozen=True)
class HistogramBin:
    """One bar of the arrival-pattern histogram: bucket start label + count."""

    label: str  # "08:30" — bucket start, HH:MM
    count: int


@dataclass(frozen=True)
class AttendanceReport:
    """The whole report: summary + one section per employee."""

    title: str
    period_label: str
    generated_label: str
    stats: list[ReportStat]
    # Arrival-pattern histogram over every first sign-in on attended days,
    # 30-minute buckets — the export counterpart of the dashboard's arrival
    # chart. Empty when the period has no arrivals.
    arrival_histogram: list[HistogramBin]
    overview_columns: list[str]
    overview_rows: list[list[str]]  # aligned to overview_columns; one per section
    sections: list[EmployeeSection]


# Overview table column order — `_overview_row` must stay aligned to this.
OVERVIEW_COLUMNS = [
    "Employee",
    "Department",
    "Attended",
    "Late",
    "Absent",
    "On leave",
    "Avg arrival",
    "Total worked",
]


def _fmt_time(value: datetime | None) -> str:
    if value is None:
        return _DASH
    return value.strftime("%H:%M")


def _fmt_minutes(minutes: int | None) -> str:
    """'7h 54m' from a minutes count, or '—' (matches frontend formatWorkedMinutes)."""
    if minutes is None:
        return _DASH
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m"


def _fmt_ddmmyyyy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _fmt_avg_minutes_of_day(samples: list[int]) -> str:
    """Mean minutes-of-day → 'HH:MM', or '—' when there are no samples."""
    if not samples:
        return _DASH
    avg = round(sum(samples) / len(samples))
    h, m = divmod(avg, 60)
    return f"{h:02d}:{m:02d}"


def _fmt_pct(numer: int, denom: int) -> str:
    if denom <= 0:
        return _DASH
    return f"{round(100 * numer / denom)}%"


def _minutes_of_day(value: datetime) -> int:
    return value.hour * 60 + value.minute


def _gap_status(
    day: date,
    *,
    emp_code: str,
    rule: ShiftRule,
    working: frozenset[str] | None,
) -> str:
    """Status for a day the employees service emitted no row for.

    Order matters: an employee not scheduled that weekday is on their day
    off even if it's also the org WFH weekday. When there's no schedule
    info (phase-1 `working is None`) we can only distinguish WFH weekdays
    and upcoming days.
    """
    if working is not None and emp_code not in working:
        return STATUS_DAY_OFF
    if day.weekday() in rule.wfh_weekdays:
        return STATUS_WFH
    # A past scheduled day with no row only happens when absence detection
    # is off (phase-1) or the day is still pre-cutoff — nothing to assert.
    return STATUS_UPCOMING


def _day_line(
    day: date,
    row: EmployeeWeekDay | None,
    *,
    emp_code: str,
    rule: ShiftRule,
    working: frozenset[str] | None,
) -> DayLine:
    date_label = _fmt_ddmmyyyy(day)
    weekday = day.strftime("%a")

    if row is None:
        status = _gap_status(day, emp_code=emp_code, rule=rule, working=working)
        return DayLine(date_label, weekday, status, _DASH, _DASH, _DASH, "")

    if row.on_holiday:
        status = STATUS_HOLIDAY
    elif row.on_leave:
        status = STATUS_ON_LEAVE
    elif row.absent:
        status = STATUS_ABSENT
    else:
        # A worked day. Lateness never fires on WFH weekdays — same rule the
        # dashboard exception detectors apply.
        late_min = 0
        if row.punch_in is not None and day.weekday() not in rule.wfh_weekdays:
            late_min = shift_rules.minutes_late(row.punch_in, rule, day)
        status = STATUS_LATE if late_min >= 1 else STATUS_PRESENT
        return DayLine(
            date_label,
            weekday,
            status,
            _fmt_time(row.punch_in),
            _fmt_time(row.punch_out),
            _fmt_minutes(row.worked_minutes),
            f"{late_min}m" if late_min >= 1 else "",
        )

    # Excused / absent day. Punch times stay visible when present (someone
    # who popped in on a leave day), same as the on-screen tables.
    return DayLine(
        date_label,
        weekday,
        status,
        _fmt_time(row.punch_in),
        _fmt_time(row.punch_out),
        _DASH,
        "",
    )


def _overview_row(s: EmployeeSection) -> list[str]:
    return [
        s.name,
        s.department or _DASH,
        str(s.days_attended),
        str(s.days_late),
        str(s.days_absent),
        str(s.days_on_leave),
        s.avg_arrival,
        s.total_worked,
    ]


def build_attendance_report(
    response: EmployeesWeekResponse,
    *,
    days: list[date],
    rule: ShiftRule,
    period_label: str,
    generated_on: date,
    department_by_emp_code: Mapping[str, str],
    working_emp_codes_by_day: Mapping[date, frozenset[str] | None] | None = None,
    emp_codes: frozenset[str] | None = None,
) -> AttendanceReport:
    """Shape the employees response into the two-level report.

    `emp_codes` is the user's selection from the report dialog — only those
    employees get a section and count toward the summary stats. None means
    everyone in the response.

    Sections are sorted by name (a report reads alphabetically; the
    emp-code-descending order of the on-screen table is a scanning
    convention, not a reading one).
    """
    working_by_day = working_emp_codes_by_day or {}

    selected = [
        emp
        for emp in response.rows
        if emp_codes is None or emp.emp_code in emp_codes
    ]
    selected.sort(key=lambda emp: emp.name.casefold())

    sections: list[EmployeeSection] = []
    # Org-wide accumulators for the summary stats.
    org_arrivals: list[int] = []
    org_attended = org_late = org_absent = org_leave = org_holiday = 0
    org_worked_minutes = 0

    for emp in selected:
        by_iso = {d.date: d for d in emp.days}
        lines: list[DayLine] = []
        arrivals: list[int] = []
        attended = late = absent = leave = holiday = missing_out = 0
        worked_minutes = 0

        for day in days:
            row = by_iso.get(day.isoformat())
            line = _day_line(
                day,
                row,
                emp_code=emp.emp_code,
                rule=rule,
                working=working_by_day.get(day),
            )
            lines.append(line)

            if line.status in (STATUS_PRESENT, STATUS_LATE):
                attended += 1
                if line.status == STATUS_LATE:
                    late += 1
                if row is not None:
                    if row.punch_in is not None:
                        arrivals.append(_minutes_of_day(row.punch_in))
                        if row.punch_out is None:
                            missing_out += 1
                    if row.worked_minutes is not None:
                        worked_minutes += row.worked_minutes
            elif line.status == STATUS_ABSENT:
                absent += 1
            elif line.status == STATUS_ON_LEAVE:
                leave += 1
            elif line.status == STATUS_HOLIDAY:
                holiday += 1

        expected = attended + absent
        sections.append(
            EmployeeSection(
                emp_code=emp.emp_code,
                name=emp.name,
                department=department_by_emp_code.get(emp.emp_code, ""),
                days_expected=expected,
                days_attended=attended,
                days_late=late,
                days_absent=absent,
                days_on_leave=leave,
                days_holiday=holiday,
                missing_signouts=missing_out,
                avg_arrival=_fmt_avg_minutes_of_day(arrivals),
                total_worked=_fmt_minutes(worked_minutes),
                avg_worked=(
                    _fmt_minutes(round(worked_minutes / attended))
                    if attended and worked_minutes
                    else _DASH
                ),
                attendance_pct=_fmt_pct(attended, expected),
                days=lines,
            )
        )

        org_arrivals.extend(arrivals)
        org_attended += attended
        org_late += late
        org_absent += absent
        org_leave += leave
        org_holiday += holiday
        org_worked_minutes += worked_minutes

    stats = _summary_stats(
        n_employees=len(sections),
        n_days=len(days),
        arrivals=org_arrivals,
        attended=org_attended,
        late=org_late,
        absent=org_absent,
        leave=org_leave,
        holiday=org_holiday,
        worked_minutes=org_worked_minutes,
    )

    return AttendanceReport(
        title="Attendance Report",
        period_label=period_label,
        generated_label=f"Generated {_fmt_ddmmyyyy(generated_on)}",
        stats=stats,
        arrival_histogram=_arrival_histogram(org_arrivals),
        overview_columns=list(OVERVIEW_COLUMNS),
        overview_rows=[_overview_row(s) for s in sections],
        sections=sections,
    )


_HISTOGRAM_BUCKET_MINUTES = 30


def _arrival_histogram(arrivals: list[int]) -> list[HistogramBin]:
    """Bucket arrival minutes-of-day into fixed 30-minute windows.

    Spans from the bucket containing the earliest arrival to the one
    containing the latest, with empty buckets in between kept so the shape
    reads correctly (a gap at 10:00 matters). Mirrors the dashboard's
    arrival chart bucketing.
    """
    if not arrivals:
        return []
    step = _HISTOGRAM_BUCKET_MINUTES
    first = (min(arrivals) // step) * step
    last = (max(arrivals) // step) * step
    bins: list[HistogramBin] = []
    for start in range(first, last + step, step):
        count = sum(1 for a in arrivals if start <= a < start + step)
        h, m = divmod(start, 60)
        bins.append(HistogramBin(label=f"{h:02d}:{m:02d}", count=count))
    return bins


def _summary_stats(
    *,
    n_employees: int,
    n_days: int,
    arrivals: list[int],
    attended: int,
    late: int,
    absent: int,
    leave: int,
    holiday: int,
    worked_minutes: int,
) -> list[ReportStat]:
    """The headline tiles on the summary sheet/page."""
    expected = attended + absent

    def per_emp(count: int) -> str:
        if n_employees == 0:
            return ""
        return f"{count / n_employees:.1f} per employee"

    avg_worked_detail = ""
    if attended and worked_minutes:
        avg_worked_detail = f"{_fmt_minutes(round(worked_minutes / attended))} per attended day"

    total_h, total_m = divmod(worked_minutes, 60)
    return [
        ReportStat("Employees", str(n_employees), f"{n_days} days in period"),
        ReportStat(
            "Attendance rate",
            _fmt_pct(attended, expected),
            f"{attended} attended of {expected} expected office days",
        ),
        ReportStat(
            "Avg arrival",
            _fmt_avg_minutes_of_day(arrivals),
            "mean first sign-in across attended days",
        ),
        ReportStat("Absences", f"{absent}", per_emp(absent)),
        ReportStat("Late arrivals", f"{late}", per_emp(late)),
        ReportStat(
            "Time off",
            f"{leave} on leave",
            f"{holiday} public-holiday days" if holiday else "",
        ),
        ReportStat(
            "Hours worked",
            f"{total_h}h {total_m:02d}m",
            avg_worked_detail,
        ),
    ]
