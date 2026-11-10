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
screen and file always agree.

WFH days come from each employee's shift (see `app.shared.wfh`), not from
a WFH request log: the "WFH days" figure counts scheduled WFH days up to the
report date on which the employee didn't come in and wasn't on leave or a
public holiday. The section's `wfh_label` names those weekdays so the
figure is read as shift-based.

NOTE — template fields not yet tracked by this system:
  - Position / Line manager: not in the Odoo payload we mirror.
  - Missing sign-ins: punches are collapsed to first/last per day, so a
    missing *first* punch is indistinguishable from a normal arrival. The
    "Missing sign-in/out" figures therefore count missing sign-*outs* only.
When those land (phase 3 Odoo work), extend `EmployeeSection` here and both
renderers pick them up automatically.

Shift end has no dedicated config field; it's derived as
`start + full_day_minutes` (09:00 + 8h = 17:00 with the org default), which
drives the departure buckets and the on-time-departure metrics.

No I/O. No datetime.now(). Everything needed comes in as arguments.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime

from app.features.employees.models import EmployeesWeekResponse, EmployeeWeekDay
from app.shared import shift_rules
from app.shared.models import ShiftRule
from app.shared.wfh import is_wfh

# Day statuses. Present/Late/Absent/On leave/Holiday mirror the on-screen
# pills; WFH / Day off / Upcoming fill the calendar gaps the screen doesn't
# show (the reference workbook lists every day in the period).
STATUS_PRESENT = "Present"
STATUS_LATE = "Late"
STATUS_ABSENT = "Absent"
STATUS_ON_LEAVE = "On leave"
STATUS_HOLIDAY = "Holiday"
# A scheduled WFH day per the employee's shift (up to the report date) with
# no office punch and no leave/holiday.
STATUS_WFH = "WFH"
# A day the employee's own schedule doesn't cover. Not a fixed Fri/Sat: shift
# patterns differ, so someone working Fri–Sat has their weekend on Sun–Mon.
# Distinct from `STATUS_ON_LEAVE`, which is a day they *were* scheduled to
# work and took off.
STATUS_WEEKEND = "Weekend"
STATUS_DAY_OFF = "Day off"  # unscheduled, but no schedule data to confirm
STATUS_UPCOMING = "—"  # day hasn't happened yet (or today, pre-cutoff)

# Placeholder for "no value" across both renderers.
DASH = "—"
_DASH = DASH  # internal alias; keeps the existing call sites terse


@dataclass(frozen=True)
class DayLine:
    """One calendar day on an employee's sheet/page."""

    date: str  # "01/06/2026" (DD/MM/YYYY per org convention)
    weekday: str  # "Mon"
    status: str  # one of the STATUS_* constants
    check_in: str  # "09:05" or "—"
    check_out: str  # "17:30" or "—"
    worked: str  # "8h 25m" or "—"
    late_by: str  # "23m" when late, else ""
    missing_hours: str  # shortfall against the full day, "0h 14m" or "—"


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
    pod: str  # Odoo `x_studio_pod`; "" when unset
    schedule_label: str  # "Sun – Thu" or "—" without schedule data
    wfh_label: str  # the shift's WFH weekdays in the period, "Thu, Fri" or "—"
    shift_start: str  # "09:00"
    shift_end: str  # "17:00" — derived from start + full_day_minutes
    days_expected: int
    days_attended: int  # includes late days
    days_late: int
    days_absent: int
    days_on_leave: int
    days_holiday: int
    missing_signouts: int  # attended days with a first punch but no last
    days_on_time: int  # attended days arriving within grace
    departures_on_time: int  # sign-outs at/after shift end
    departures_recorded: int  # attended days with a sign-out at all
    # Shortfall against `full_day_minutes` summed over attended days, floored
    # at zero per day (overtime on one day never offsets a short day).
    missing_minutes: int
    days_wfh: int  # STATUS_WFH days: shift WFH days, up to the report date
    avg_arrival: str  # "09:12" or "—"
    avg_departure: str  # "17:04" or "—"
    total_worked: str  # "142h 20m"
    expected_worked: str  # full-day × expected days, "32h 00m"
    avg_worked: str  # per attended day, "7h 06m" or "—"
    full_day: str  # the daily target itself, "8h 00m"
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
class RankingEntry:
    """One row of a Top Rankings column: employee + their formatted value."""

    name: str
    value: str


@dataclass(frozen=True)
class Ranking:
    """One Top Rankings column — a title and its podium (up to 3 entries)."""

    title: str
    entries: list[RankingEntry]


@dataclass(frozen=True)
class KeyMetric:
    """One of the four headline tiles at the top of the summary sheet."""

    label: str
    value: str
    detail: str


@dataclass(frozen=True)
class AttendanceReport:
    """The whole report: summary + one section per employee."""

    title: str
    subtitle: str
    period_label: str
    generated_label: str  # "Generated 19-07-2026" — PDF/page caption
    generated_on: str  # "19/07/2026" — bare date for the summary meta block
    employee_count: int
    # The four hero tiles across the top of the summary sheet.
    key_metrics: list[KeyMetric]
    stats: list[ReportStat]
    # Fixed-window arrival/departure distributions for both renderers'
    # side-by-side pattern tables and charts (see `_ARRIVAL_OFFSETS` /
    # `_DEPARTURE_OFFSETS`). Always the full window list; counts are zero
    # when the period has no samples.
    arrival_buckets: list[HistogramBin]
    departure_buckets: list[HistogramBin]
    rankings: list[Ranking]
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


def _parse_hhmm(value: str) -> int:
    """'09:00' → 540 minutes-of-day."""
    hours, _, minutes = value.partition(":")
    return int(hours) * 60 + int(minutes)


def _shift_start_minutes(rule: ShiftRule) -> int:
    return _parse_hhmm(rule.start)


def _shift_end_minutes(rule: ShiftRule) -> int:
    """Shift end derived from the configured start + expected day length.

    There is no explicit `end` in the shift rules (phase 1 tracks arrival,
    not departure), so the workday's nominal close is start + full-day. With
    the org default that's 09:00 + 8h = 17:00, and it follows the config if
    either value changes.
    """
    return _shift_start_minutes(rule) + rule.full_day_minutes


def _fmt_hhmm(minutes: int) -> str:
    h, m = divmod(minutes % (24 * 60), 60)
    return f"{h:02d}:{m:02d}"


# Fixed-window distributions for the summary sheet. Both are expressed as
# offsets in minutes relative to the shift boundary, so they track the
# configured shift instead of hardcoding 09:00/17:00. Each entry is
# (label-builder, lower-offset, upper-offset); the first bucket is
# open-ended below and the last open-ended above.
_ARRIVAL_OFFSETS: list[tuple[int | None, int | None]] = [
    (-30, 0),  # 08:30–09:00
    (0, 15),  # 09:00–09:15
    (15, 30),  # 09:15–09:30
    (30, 45),  # 09:30–09:45
    (45, 60),  # 09:45–10:00
    (60, 90),  # 10:00–10:30
    (90, None),  # 10:30+
]

_DEPARTURE_OFFSETS: list[tuple[int | None, int | None]] = [
    (None, -30),  # before 16:30
    (-30, -15),  # 16:30–16:45
    (-15, 0),  # 16:45–17:00
    (0, 15),  # 17:00–17:15
    (15, 30),  # 17:15–17:30
    (30, 45),  # 17:30–17:45
    (45, None),  # 17:45+
]


def _bucket_label(anchor: int, low: int | None, high: int | None) -> str:
    if low is None:
        return f"Before {_fmt_hhmm(anchor + (high or 0))}"
    if high is None:
        return f"{_fmt_hhmm(anchor + low)}+"
    return f"{_fmt_hhmm(anchor + low)}–{_fmt_hhmm(anchor + high)}"


def _fixed_buckets(
    samples: list[int],
    *,
    anchor: int,
    offsets: list[tuple[int | None, int | None]],
) -> list[HistogramBin]:
    """Distribute minutes-of-day samples into the fixed windows.

    Bounds are half-open [low, high) relative to `anchor`; the first bucket
    catches everything below its upper edge and the last everything at or
    above its lower edge, so every sample lands in exactly one bucket.
    """
    bins: list[HistogramBin] = []
    for low, high in offsets:
        lo = None if low is None else anchor + low
        hi = None if high is None else anchor + high
        count = sum(
            1
            for s in samples
            if (lo is None or s >= lo) and (hi is None or s < hi)
        )
        bins.append(HistogramBin(label=_bucket_label(anchor, low, high), count=count))
    return bins


def _gap_status(
    day: date,
    *,
    emp_code: str,
    working: frozenset[str] | None,
    wfh: bool,
    today: date,
) -> str:
    """Status for a day the employees service emitted no row for.

    Order matters: an employee not scheduled that day is on their weekend
    (a WFH day is always inside the shift, so the two never truly collide).
    A WFH day only reads as WFH once it has arrived; a future one is
    upcoming like any other scheduled day, so "WFH days" never counts days
    that haven't happened.
    """
    if working is not None and emp_code not in working:
        return STATUS_WEEKEND
    if wfh and day <= today:
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
    wfh: bool,
    today: date,
) -> DayLine:
    date_label = day.strftime("%d/%m/%Y")
    weekday = day.strftime("%a")

    if row is None:
        status = _gap_status(
            day, emp_code=emp_code, working=working, wfh=wfh, today=today
        )
        return DayLine(
            date_label, weekday, status, _DASH, _DASH, _DASH, "", _DASH
        )

    if row.on_holiday:
        status = STATUS_HOLIDAY
    elif row.on_leave:
        status = STATUS_ON_LEAVE
    elif row.absent:
        status = STATUS_ABSENT
    else:
        # A worked day. On the employee's WFH day an office visit is
        # voluntary: never late and no missing hours — the same rules the
        # dashboard's late and incomplete-hours detectors apply.
        late_min = 0
        if row.punch_in is not None and not wfh:
            late_min = shift_rules.minutes_late(row.punch_in, rule, day)
        status = STATUS_LATE if late_min >= 1 else STATUS_PRESENT
        # Shortfall against the full day, floored at zero — a long day reads
        # as "nothing missing", never as negative missing hours.
        missing = _DASH
        if row.worked_minutes is not None and not wfh:
            missing = _fmt_minutes(max(0, rule.full_day_minutes - row.worked_minutes))
        return DayLine(
            date_label,
            weekday,
            status,
            _fmt_time(row.punch_in),
            _fmt_time(row.punch_out),
            _fmt_minutes(row.worked_minutes),
            f"{late_min}m" if late_min >= 1 else "",
            missing,
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
        _DASH,
    )


_WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _schedule_label(
    emp_code: str,
    days: list[date],
    working_by_day: Mapping[date, frozenset[str] | None],
) -> str:
    """The employee's working week, e.g. "Sun – Thu" or "Sun, Tue, Thu".

    Derived from the days in the period their own schedule covers, so a
    Fri–Sat worker reads correctly rather than assuming the org default.
    Contiguous runs (wrapping Sun→Sat) collapse to a range; anything else
    lists the days. "—" when the period carries no schedule data.
    """
    weekdays = {
        day.weekday()
        for day in days
        if (working := working_by_day.get(day)) is not None and emp_code in working
    }
    if not weekdays:
        return _DASH
    if len(weekdays) == 7:
        return "Every day"

    # Rotate so the run starts at a weekday whose predecessor is off, then
    # a single unbroken block means the pattern is a range.
    start = next(d for d in range(7) if d in weekdays and (d - 1) % 7 not in weekdays)
    ordered = [(start + i) % 7 for i in range(7)]
    run = [d for d in ordered if d in weekdays]
    contiguous = all(
        (run[i] + 1) % 7 == run[i + 1] for i in range(len(run) - 1)
    )
    if len(run) == 1:
        return _WEEKDAY_NAMES[run[0]]
    if contiguous:
        return f"{_WEEKDAY_NAMES[run[0]]} – {_WEEKDAY_NAMES[run[-1]]}"
    return ", ".join(_WEEKDAY_NAMES[d] for d in run)


# Prezlab's week runs Sun–Sat (see `week_range_for`), so list days that way.
_WEEK_ORDER = [6, 0, 1, 2, 3, 4, 5]


def _wfh_label(weekdays: set[int]) -> str:
    """The shift's WFH weekdays as a plain list: "Thu", "Thu, Fri", or "—".

    Always a list, never a range: "Thu, Fri" reads more plainly than
    "Thu – Fri" for the two- and three-day patterns in use.
    """
    if not weekdays:
        return _DASH
    return ", ".join(_WEEKDAY_NAMES[d] for d in _WEEK_ORDER if d in weekdays)


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
    pod_by_emp_code: Mapping[str, str] | None = None,
    working_emp_codes_by_day: Mapping[date, frozenset[str] | None] | None = None,
    emp_codes: frozenset[str] | None = None,
    wfh_emp_codes_by_day: Mapping[date, frozenset[str] | None] | None = None,
) -> AttendanceReport:
    """Shape the employees response into the two-level report.

    `emp_codes` is the user's selection from the report dialog — only those
    employees get a section and count toward the summary stats. None means
    everyone in the response.

    `wfh_emp_codes_by_day` is the roster's per-day WFH set (from each
    employee's shift); a missing day or map falls back to the org-wide
    `rule.wfh_weekdays`.

    Sections are sorted by name (a report reads alphabetically; the
    emp-code-descending order of the on-screen table is a scanning
    convention, not a reading one).
    """
    working_by_day = working_emp_codes_by_day or {}
    wfh_by_day = wfh_emp_codes_by_day or {}
    pods = pod_by_emp_code or {}

    selected = [
        emp
        for emp in response.rows
        if emp_codes is None or emp.emp_code in emp_codes
    ]
    selected.sort(key=lambda emp: emp.name.casefold())

    shift_end = _shift_end_minutes(rule)

    sections: list[EmployeeSection] = []
    # Org-wide accumulators for the summary stats.
    org_arrivals: list[int] = []
    org_departures: list[int] = []
    org_attended = org_late = org_absent = org_leave = org_holiday = 0
    org_on_time = org_dep_on_time = org_dep_recorded = 0
    org_worked_minutes = 0

    for emp in selected:
        by_iso = {d.date: d for d in emp.days}
        lines: list[DayLine] = []
        arrivals: list[int] = []
        departures: list[int] = []
        attended = late = absent = leave = holiday = missing_out = 0
        dep_on_time = dep_recorded = wfh = 0
        worked_minutes = missing_minutes = 0
        wfh_weekdays: set[int] = set()

        for day in days:
            row = by_iso.get(day.isoformat())
            working = working_by_day.get(day)
            day_is_wfh = is_wfh(
                emp.emp_code, day, wfh_by_day.get(day), rule.wfh_weekdays
            )
            if day_is_wfh and (working is None or emp.emp_code in working):
                wfh_weekdays.add(day.weekday())
            line = _day_line(
                day,
                row,
                emp_code=emp.emp_code,
                rule=rule,
                working=working,
                wfh=day_is_wfh,
                today=generated_on,
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
                    if row.punch_out is not None:
                        out_minutes = _minutes_of_day(row.punch_out)
                        departures.append(out_minutes)
                        dep_recorded += 1
                        if out_minutes >= shift_end:
                            dep_on_time += 1
                    if row.worked_minutes is not None:
                        worked_minutes += row.worked_minutes
                        # A short office visit on a WFH day isn't a short day.
                        if not day_is_wfh:
                            missing_minutes += max(
                                0, rule.full_day_minutes - row.worked_minutes
                            )
            elif line.status == STATUS_ABSENT:
                absent += 1
            elif line.status == STATUS_ON_LEAVE:
                leave += 1
            elif line.status == STATUS_HOLIDAY:
                holiday += 1
            elif line.status == STATUS_WFH:
                wfh += 1

        expected = attended + absent
        on_time = attended - late
        sections.append(
            EmployeeSection(
                emp_code=emp.emp_code,
                name=emp.name,
                department=department_by_emp_code.get(emp.emp_code, ""),
                pod=pods.get(emp.emp_code, ""),
                schedule_label=_schedule_label(emp.emp_code, days, working_by_day),
                wfh_label=_wfh_label(wfh_weekdays),
                shift_start=_fmt_hhmm(_shift_start_minutes(rule)),
                shift_end=_fmt_hhmm(shift_end),
                days_expected=expected,
                days_attended=attended,
                days_late=late,
                days_absent=absent,
                days_on_leave=leave,
                days_holiday=holiday,
                missing_signouts=missing_out,
                days_on_time=on_time,
                departures_on_time=dep_on_time,
                departures_recorded=dep_recorded,
                missing_minutes=missing_minutes,
                days_wfh=wfh,
                avg_arrival=_fmt_avg_minutes_of_day(arrivals),
                avg_departure=_fmt_avg_minutes_of_day(departures),
                total_worked=_fmt_minutes(worked_minutes),
                expected_worked=_fmt_minutes(expected * rule.full_day_minutes),
                avg_worked=(
                    _fmt_minutes(round(worked_minutes / attended))
                    if attended and worked_minutes
                    else _DASH
                ),
                full_day=_fmt_minutes(rule.full_day_minutes),
                attendance_pct=_fmt_pct(attended, expected),
                days=lines,
            )
        )

        org_arrivals.extend(arrivals)
        org_departures.extend(departures)
        org_attended += attended
        org_late += late
        org_absent += absent
        org_leave += leave
        org_holiday += holiday
        org_on_time += on_time
        org_dep_on_time += dep_on_time
        org_dep_recorded += dep_recorded
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
        subtitle="Team Summary",
        period_label=period_label,
        generated_label=f"Generated {_fmt_ddmmyyyy(generated_on)}",
        generated_on=generated_on.strftime("%d/%m/%Y"),
        employee_count=len(sections),
        key_metrics=_key_metrics(
            n_employees=len(sections),
            attended=org_attended,
            absent=org_absent,
            on_time=org_on_time,
            dep_on_time=org_dep_on_time,
            dep_recorded=org_dep_recorded,
        ),
        stats=stats,
        arrival_buckets=_fixed_buckets(
            org_arrivals,
            anchor=_shift_start_minutes(rule),
            offsets=_ARRIVAL_OFFSETS,
        ),
        departure_buckets=_fixed_buckets(
            org_departures, anchor=shift_end, offsets=_DEPARTURE_OFFSETS
        ),
        rankings=_rankings(sections),
        overview_columns=list(OVERVIEW_COLUMNS),
        overview_rows=[_overview_row(s) for s in sections],
        sections=sections,
    )


def _key_metrics(
    *,
    n_employees: int,
    attended: int,
    absent: int,
    on_time: int,
    dep_on_time: int,
    dep_recorded: int,
) -> list[KeyMetric]:
    """The four hero tiles: attendance, punctuality, departures, headcount."""
    expected = attended + absent
    return [
        KeyMetric(
            "Attendance rate",
            _fmt_pct(attended, expected),
            "Attended ÷ expected office days",
        ),
        KeyMetric(
            "Punctuality rate",
            _fmt_pct(on_time, attended),
            "On-time ÷ present days",
        ),
        KeyMetric(
            "On-time departures",
            _fmt_pct(dep_on_time, dep_recorded),
            "Left at/after shift end",
        ),
        KeyMetric("Total employees", str(n_employees), "In this report"),
    ]


_RANKING_SIZE = 3


def _rankings(sections: list[EmployeeSection]) -> list[Ranking]:
    """The four Top Rankings podiums.

    Each is the top `_RANKING_SIZE` employees by one measure, ties broken by
    name so the order is stable. Employees scoring zero are left out — a
    podium of zeroes says nothing — which is why a column can come back with
    fewer than three entries (the renderer pads with em-dashes).
    """

    def podium(
        key, fmt, title: str
    ) -> Ranking:
        ranked = sorted(
            (s for s in sections if key(s) > 0),
            key=lambda s: (-key(s), s.name.casefold()),
        )[:_RANKING_SIZE]
        return Ranking(
            title=title,
            entries=[RankingEntry(s.name, fmt(key(s))) for s in ranked],
        )

    return [
        podium(lambda s: s.days_absent, str, "Top Absentees"),
        podium(lambda s: s.days_late, str, "Most Late Arrivals"),
        podium(lambda s: s.missing_minutes, _fmt_minutes, "Most Hours Missing"),
        podium(lambda s: s.missing_signouts, str, "Missing Sign-in/out"),
    ]


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
