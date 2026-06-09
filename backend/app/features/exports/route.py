"""Export routes — download the Employees attendance data as Excel or PDF.

One endpoint, `GET /api/exports/employees`, parameterized by the same
`mode`/`date`/`start`/`end` the Employees page uses, so it always exports
exactly "the period being viewed". The view→data mapping is identical to the
employees routes (daily → today, weekly/monthly → derived range, custom →
explicit range): we reuse `build_employees_today` / `build_employees_week`
rather than re-deriving anything, then hand the response to the export
service + the chosen renderer.

The file is returned as a streamed download with a descriptive,
range-stamped filename.
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_punch_repo, get_roster, now_in_tz, parse_date
from app.infra.roster import RosterProvider
from app.infra.supabase_client import PunchRepository
from app.shared.date_range import iter_days, month_range_for, week_range_for

from app.features.employees.service import (
    build_employees_today,
    build_employees_week,
)
from app.features.exports.excel import render_xlsx
from app.features.exports.pdf import render_pdf
from app.features.exports.service import build_daily_export, build_range_export

router = APIRouter(tags=["exports"])

ExportFormat = Literal["excel", "pdf"]
Mode = Literal["daily", "weekly", "monthly", "custom"]

# Same defensive cap the employees range endpoint enforces — a quarter is
# almost certainly a mistake and risks slow Supabase queries.
_MAX_RANGE_DAYS = 95

_XLSX_MEDIA = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_PDF_MEDIA = "application/pdf"


@router.get("/exports/employees")
def export_employees(
    fmt: ExportFormat = Query(default="excel", alias="format"),
    mode: Mode = Query(default="daily"),
    day: date = Depends(parse_date),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    now: datetime = Depends(now_in_tz),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> StreamingResponse:
    # Resolve the same (start, end, is_single_day) the Employees page renders.
    s, e, single_day = _resolve_range(mode, day, start, end)
    if (e - s).days > _MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail="Range too large; max 95 days.")

    if single_day:
        table = _build_daily_table(s, now, roster, repo)
    else:
        table = _build_range_table(s, e, now, roster, repo)

    if fmt == "pdf":
        payload = render_pdf(table)
        media_type = _PDF_MEDIA
        ext = "pdf"
    else:
        payload = render_xlsx(table)
        media_type = _XLSX_MEDIA
        ext = "xlsx"

    filename = _filename(s, e, single_day, ext)
    return StreamingResponse(
        BytesIO(payload),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _resolve_range(
    mode: Mode,
    day: date,
    start: date | None,
    end: date | None,
) -> tuple[date, date, bool]:
    """Map the view mode to (start, end, single_day).

    Mirrors the dashboard/employees route conventions:
      - daily            → (day, day, single)
      - weekly           → Sun–Sat week containing `day`
      - monthly          → calendar month of `day`
      - custom           → explicit [start, end]; a single-day or reversed
                           pick collapses/normalizes the same way the
                           dashboard route handles it.
    """
    if mode == "custom":
        s = start or day
        e = end or s
        if s > e:
            s, e = e, s
        return s, e, s == e
    if mode == "monthly":
        s, e = month_range_for(day)
        return s, e, False
    if mode == "weekly":
        s, e = week_range_for(day)
        return s, e, False
    return day, day, True


def _build_daily_table(
    day: date,
    now: datetime,
    roster: RosterProvider,
    repo: PunchRepository,
):
    """Build the daily export table — same data the Employees daily table shows."""
    punches = repo.punches_for_day(day)
    employees = roster.employees_from_punches(punches)
    leave_by_day = roster.on_leave_emp_codes_for_range(day, day)
    on_leave = leave_by_day.get(day) if leave_by_day is not None else None
    holiday_by_day = roster.holiday_emp_codes_for_range(day, day)
    on_holiday = holiday_by_day.get(day) if holiday_by_day is not None else None
    response = build_employees_today(
        employees=employees,
        punches=punches,
        day=day,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        rule=roster.default_shift(),
        now=now,
        working_emp_codes=roster.working_emp_codes_for(day),
        on_leave_emp_codes=on_leave,
        on_holiday_emp_codes=on_holiday,
    )
    return build_daily_export(response, period_label=_period_label(day, day, True))


def _build_range_table(
    start: date,
    end: date,
    now: datetime,
    roster: RosterProvider,
    repo: PunchRepository,
):
    """Build the grouped export table — same data the weekly/monthly/custom tables show."""
    days = iter_days(start, end)
    punches_by_day = repo.punches_grouped_by_day(start, end)
    all_punches = [p for plist in punches_by_day.values() for p in plist]
    employees = roster.employees_from_punches(all_punches)
    working_by_day = {d: roster.working_emp_codes_for(d) for d in days}
    leave_by_day = roster.on_leave_emp_codes_for_range(start, end)
    holiday_by_day = roster.holiday_emp_codes_for_range(start, end)
    response = build_employees_week(
        employees=employees,
        punches_by_day=punches_by_day,
        days=days,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        rule=roster.default_shift(),
        now=now,
        working_emp_codes_by_day=working_by_day,
        on_leave_emp_codes_by_day=leave_by_day,
        on_holiday_emp_codes_by_day=holiday_by_day,
    )
    return build_range_export(
        response, period_label=_period_label(start, end, False)
    )


def _period_label(start: date, end: date, single_day: bool) -> str:
    """Human-readable caption for the sheet/page, DD-MM-YYYY per convention."""
    if single_day:
        return start.strftime("%A, %d-%m-%Y")
    return f"{start.strftime('%d-%m-%Y')} to {end.strftime('%d-%m-%Y')}"


def _filename(start: date, end: date, single_day: bool, ext: str) -> str:
    """Descriptive, range-stamped download filename.

    Single day  → prezlab-attendance_2026-06-09.xlsx
    Range       → prezlab-attendance_2026-06-01_to_2026-06-30.pdf

    ISO dates here (sortable on disk); the in-file caption uses DD-MM-YYYY.
    """
    if single_day:
        stamp = start.isoformat()
    else:
        stamp = f"{start.isoformat()}_to_{end.isoformat()}"
    return f"prezlab-attendance_{stamp}.{ext}"
