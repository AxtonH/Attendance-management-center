"""Export routes — attendance reports as Excel or PDF, plus the roster
options the report dialog needs.

`GET /api/exports/employees` is parameterized by the same `mode`/`date`/
`start`/`end` the pages use, plus an optional `emp_codes` selection (comma-
separated) from the report dialog — omitted means everyone. Daily and range
views share one path: both build the per-day `EmployeesWeekResponse` (a
single-day range for daily) and hand it to `build_attendance_report`, so the
summary/per-employee report shape is identical regardless of period length.

`GET /api/exports/roster` returns the employees (code, name, department)
available for selection in the dialog. Odoo roster when configured; punch-
derived for the requested period as the phase-1 fallback.
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import get_punch_repo, get_roster, now_in_tz, parse_date
from app.infra.roster import RosterProvider
from app.infra.supabase_client import PunchRepository
from app.shared.date_range import iter_days, month_range_for, week_range_for

from app.features.employees.service import build_employees_week
from app.features.exports.excel import render_xlsx
from app.features.exports.pdf import render_pdf
from app.features.exports.report import build_attendance_report

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


class RosterEmployee(BaseModel):
    emp_code: str
    name: str
    department: str


class ExportRosterResponse(BaseModel):
    employees: list[RosterEmployee]


@router.get("/exports/employees")
def export_employees(
    fmt: ExportFormat = Query(default="excel", alias="format"),
    mode: Mode = Query(default="daily"),
    day: date = Depends(parse_date),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    emp_codes: str | None = Query(default=None),
    now: datetime = Depends(now_in_tz),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> StreamingResponse:
    # Resolve the same (start, end) the pages render for this mode.
    s, e, single_day = _resolve_range(mode, day, start, end)
    if (e - s).days > _MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail="Range too large; max 95 days.")

    selection = _parse_emp_codes(emp_codes)

    days = iter_days(s, e)
    punches_by_day = repo.punches_grouped_by_day(s, e)
    all_punches = [p for plist in punches_by_day.values() for p in plist]
    employees = roster.employees_from_punches(all_punches)
    working_by_day = {d: roster.working_emp_codes_for(d) for d in days}
    response = build_employees_week(
        employees=employees,
        punches_by_day=punches_by_day,
        days=days,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        rule=roster.default_shift(),
        now=now,
        working_emp_codes_by_day=working_by_day,
        on_leave_emp_codes_by_day=roster.on_leave_emp_codes_for_range(s, e),
        on_holiday_emp_codes_by_day=roster.holiday_emp_codes_for_range(s, e),
    )

    report = build_attendance_report(
        response,
        days=days,
        rule=roster.default_shift(),
        period_label=_period_label(s, e, single_day),
        generated_on=now.date(),
        department_by_emp_code=roster.department_by_emp_code(),
        pod_by_emp_code=roster.pod_by_emp_code(),
        working_emp_codes_by_day=working_by_day,
        emp_codes=selection,
    )

    if fmt == "pdf":
        payload = render_pdf(report)
        media_type = _PDF_MEDIA
        ext = "pdf"
    else:
        payload = render_xlsx(report)
        media_type = _XLSX_MEDIA
        ext = "xlsx"

    filename = _filename(s, e, single_day, ext)
    return StreamingResponse(
        BytesIO(payload),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exports/roster", response_model=ExportRosterResponse)
def export_roster(
    mode: Mode = Query(default="daily"),
    day: date = Depends(parse_date),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> ExportRosterResponse:
    """Employees selectable in the report dialog, sorted by name.

    Odoo roster (names + departments) when configured. Phase-1 fallback:
    derive from the period's punches so the dialog still lists everyone who
    would appear in the export.
    """
    names = dict(roster.display_names())
    if names:
        expected = roster.expected_emp_codes()
        if expected is not None:
            names = {c: n for c, n in names.items() if c in expected}
    else:
        s, e, _ = _resolve_range(mode, day, start, end)
        if (e - s).days > _MAX_RANGE_DAYS:
            raise HTTPException(
                status_code=400, detail="Range too large; max 95 days."
            )
        punches_by_day = repo.punches_grouped_by_day(s, e)
        all_punches = [p for plist in punches_by_day.values() for p in plist]
        names = {
            emp.emp_code: emp.name
            for emp in roster.employees_from_punches(all_punches)
        }

    departments = roster.department_by_emp_code()
    employees = [
        RosterEmployee(
            emp_code=code, name=name, department=departments.get(code, "")
        )
        for code, name in names.items()
    ]
    employees.sort(key=lambda emp: emp.name.casefold())
    return ExportRosterResponse(employees=employees)


def _parse_emp_codes(raw: str | None) -> frozenset[str] | None:
    """Comma-separated `emp_codes` → selection set. None/blank = everyone."""
    if raw is None:
        return None
    codes = frozenset(code.strip() for code in raw.split(",") if code.strip())
    if not codes:
        return None
    return codes


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
