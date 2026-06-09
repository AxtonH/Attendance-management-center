"""Exports feature: pure functions that flatten employee attendance into a
renderer-agnostic table.

The on-screen Employees tables and these exports must always agree, so we
build the export from the *same* response models the API already returns
(`EmployeesTodayResponse` / `EmployeesWeekResponse`) rather than re-deriving
anything from punches. The route fetches those via the existing employees
service; this module only reshapes them into rows of display strings.

`ExportTable` is the single intermediate structure both the Excel and PDF
renderers consume — format-specific code (openpyxl, reportlab) never touches
attendance logic, and column/label changes happen in exactly one place.

No I/O. No datetime.now(). Everything needed comes in as arguments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.features.employees.models import (
    EmployeeDay,
    EmployeesTodayResponse,
    EmployeesWeekResponse,
)

# Status label shown in the "Status / Worked time" column. Mirrors the
# frontend pills (AbsentPill / OnLeavePill / HolidayPill) and the worked-time
# formatter so the file reads the same as the screen. Holiday wins over leave.
STATUS_PRESENT = ""  # present rows show worked time instead of a status word
STATUS_ABSENT = "Absent"
STATUS_ON_LEAVE = "On leave"
STATUS_HOLIDAY = "Holiday"


@dataclass(frozen=True)
class ExportTable:
    """A flat, renderer-agnostic view of an attendance report.

    `title` heads the sheet/page. `columns` are the header cells. `rows` is a
    list of string rows aligned to `columns`. `section_rows` holds the indices
    in `rows` that are section headers (per-employee banners in the grouped
    weekly/monthly layout) so renderers can style them distinctly; it's empty
    for the flat daily layout. `subtitle` is an optional one-line caption
    (e.g. the covered date range).
    """

    title: str
    subtitle: str
    columns: list[str]
    rows: list[list[str]]
    section_rows: set[int] = field(default_factory=set)


def _fmt_time(value: datetime | None) -> str:
    """'09:05' from a datetime, or '—' when missing (matches frontend formatTime)."""
    if value is None:
        return "—"
    return value.strftime("%H:%M")


def _fmt_worked_minutes(minutes: int | None) -> str:
    """'7h 54m' from a minutes count, or '—' (matches frontend formatWorkedMinutes)."""
    if minutes is None:
        return "—"
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m"


def _status_word(row: EmployeeDay) -> str:
    """The excused/absent label for a row, or '' for a normal worked day.

    Holiday wins over leave (same precedence the builders and UI use).
    """
    if row.on_holiday:
        return STATUS_HOLIDAY
    if row.on_leave:
        return STATUS_ON_LEAVE
    if row.absent:
        return STATUS_ABSENT
    return STATUS_PRESENT


def _worked_or_status(
    *,
    worked_minutes: int | None,
    on_holiday: bool,
    on_leave: bool,
    absent: bool,
) -> str:
    """One cell combining worked time and excused/absent status.

    Matches the on-screen "Worked time" column: a pill word when the day is
    excused/absent, otherwise the formatted duration.
    """
    if on_holiday:
        return STATUS_HOLIDAY
    if on_leave:
        return STATUS_ON_LEAVE
    if absent:
        return STATUS_ABSENT
    return _fmt_worked_minutes(worked_minutes)


def _fmt_iso_ddmmyyyy(iso: str) -> str:
    """'2026-05-18' → '18-05-2026' per Prezlab's DD-MM-YYYY convention."""
    parts = iso.split("-")
    if len(parts) != 3:
        return iso
    y, m, d = parts
    return f"{d}-{m}-{y}"


def _fmt_weekday_date(iso: str) -> str:
    """'2026-05-10' → 'Sun 10-05-2026'. Short weekday + DD-MM-YYYY.

    Mirrors the weekly table's day column (weekday + date) but uses the
    numeric DD-MM-YYYY form so the file is unambiguous regardless of locale.
    """
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.strftime('%a')} {d.strftime('%d-%m-%Y')}"


def build_daily_export(
    response: EmployeesTodayResponse,
    *,
    period_label: str,
) -> ExportTable:
    """Flat one-row-per-employee table for the daily view.

    Column shape matches the daily Employees table: Emp code, Name, Punch in,
    Punch out, Worked time / status. Rows are sorted by emp_code descending
    (numeric where possible), consistent with the on-screen sort.
    """
    columns = ["Emp code", "Name", "Punch in", "Punch out", "Worked time"]
    rows: list[list[str]] = []
    for row in _sort_rows(response.rows):
        rows.append(
            [
                row.emp_code,
                row.name,
                _fmt_time(row.punch_in),
                _fmt_time(row.punch_out),
                _worked_or_status(
                    worked_minutes=row.worked_minutes,
                    on_holiday=row.on_holiday,
                    on_leave=row.on_leave,
                    absent=row.absent,
                ),
            ]
        )
    return ExportTable(
        title="Attendance · Employees",
        subtitle=period_label,
        columns=columns,
        rows=rows,
    )


def build_range_export(
    response: EmployeesWeekResponse,
    *,
    period_label: str,
) -> ExportTable:
    """Grouped table for weekly / monthly / custom views.

    One section per employee: a banner row (emp code, name, days-worked +
    total hours) followed by the per-day breakdown. The banner row indices
    are recorded in `section_rows` so renderers can bold/shade them.

    The day columns align to the employee banner columns by position:
      [Emp code / Day, Name / —, Punch in, Punch out, Worked time]
    The banner reuses col 0 for the emp code and col 1 for the name; day
    rows put the date in col 0 and leave col 1 blank, so a single 5-column
    grid serves both the section header and its children.
    """
    columns = ["Emp code / Day", "Name", "Punch in", "Punch out", "Worked time"]
    rows: list[list[str]] = []
    section_rows: set[int] = set()

    for emp_row in response.rows:
        days_label = (
            "1 day" if emp_row.days_worked == 1 else f"{emp_row.days_worked} days"
        )
        total = _fmt_worked_minutes(emp_row.total_worked_minutes)
        # Section banner. Worked-time column carries the per-employee summary
        # ("4 days · 31h 20m") so the grouped file reads like the expandable
        # web row.
        section_rows.add(len(rows))
        rows.append(
            [
                emp_row.emp_code,
                emp_row.name,
                "",
                "",
                f"{days_label} · {total}",
            ]
        )
        for d in emp_row.days:
            rows.append(
                [
                    _fmt_weekday_date(d.date),
                    "",
                    _fmt_time(d.punch_in),
                    _fmt_time(d.punch_out),
                    _worked_or_status(
                        worked_minutes=d.worked_minutes,
                        on_holiday=d.on_holiday,
                        on_leave=d.on_leave,
                        absent=d.absent,
                    ),
                ]
            )

    return ExportTable(
        title="Attendance · Employees",
        subtitle=period_label,
        columns=columns,
        rows=rows,
        section_rows=section_rows,
    )


def _sort_rows(rows: list[EmployeeDay]) -> list[EmployeeDay]:
    """emp_code descending, numeric where possible (matches the daily table)."""

    def key(r: EmployeeDay) -> tuple[int, int | str]:
        try:
            return (0, -int(r.emp_code))
        except ValueError:
            return (1, r.emp_code)

    return sorted(rows, key=key)
