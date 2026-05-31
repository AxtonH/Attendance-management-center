"""Employees routes — daily and weekly views of attendance punches.

Both routes share the same Odoo state (cached) and the same punch
fetching primitives. Weekly costs one paginated Supabase round-trip;
daily costs one too. Zero extra Odoo calls in either path.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_punch_repo, get_roster, now_in_tz, parse_date
from app.infra.roster import RosterProvider
from app.infra.supabase_client import PunchRepository
from app.shared.date_range import iter_days, month_range_for, week_range_for

from app.features.employees.models import (
    EmployeesMonthResponse,
    EmployeesTodayResponse,
    EmployeesWeekResponse,
)
from app.features.employees.service import (
    build_employees_today,
    build_employees_week,
)

router = APIRouter(tags=["employees"])


@router.get("/employees/today", response_model=EmployeesTodayResponse)
def employees_today(
    day: date = Depends(parse_date),
    now: datetime = Depends(now_in_tz),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> EmployeesTodayResponse:
    punches = repo.punches_for_day(day)
    employees = roster.employees_from_punches(punches)
    leave_by_day = roster.on_leave_emp_codes_for_range(day, day)
    on_leave = leave_by_day.get(day) if leave_by_day is not None else None
    return build_employees_today(
        employees=employees,
        punches=punches,
        day=day,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        rule=roster.default_shift(),
        now=now,
        working_emp_codes=roster.working_emp_codes_for(day),
        on_leave_emp_codes=on_leave,
    )


@router.get("/employees/week", response_model=EmployeesWeekResponse)
def employees_week(
    day: date = Depends(parse_date),
    now: datetime = Depends(now_in_tz),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> EmployeesWeekResponse:
    """One row per employee scheduled or punched in the Sun–Sat week of `day`.

    Single paginated Supabase query for the whole week. Aggregation
    happens in memory; Odoo state is reused from cache. The shift rule
    + per-day working sets feed the per-employee expected-hours total
    (excludes WFH days, so a Sun–Thu employee expects 4 × 8h = 32h) and
    drive absent-day detection (`now` settles each day's cutoff).
    """
    start, end = week_range_for(day)
    days = iter_days(start, end)
    punches_by_day = repo.punches_grouped_by_day(start, end)
    all_punches = [p for plist in punches_by_day.values() for p in plist]
    employees = roster.employees_from_punches(all_punches)
    working_by_day = {d: roster.working_emp_codes_for(d) for d in days}
    leave_by_day = roster.on_leave_emp_codes_for_range(start, end)
    return build_employees_week(
        employees=employees,
        punches_by_day=punches_by_day,
        days=days,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        rule=roster.default_shift(),
        now=now,
        working_emp_codes_by_day=working_by_day,
        on_leave_emp_codes_by_day=leave_by_day,
    )


@router.get("/employees/month", response_model=EmployeesMonthResponse)
def employees_month(
    day: date = Depends(parse_date),
    now: datetime = Depends(now_in_tz),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> EmployeesMonthResponse:
    """One row per employee scheduled or punched in the calendar month of `day`.

    Same per-employee shape as the weekly endpoint, just over a longer
    range. We pass `rule`/`now`/`working_emp_codes_by_day` so absent days
    surface here too; the per-row `expected_*` totals they also populate
    aren't shown in monthly view (variable month length, holidays).

    Speed: one paginated Supabase query for the whole month (~5-6 pages
    for typical Prezlab data). Odoo state reused from cache.
    """
    start, end = month_range_for(day)
    days = iter_days(start, end)
    punches_by_day = repo.punches_grouped_by_day(start, end)
    all_punches = [p for plist in punches_by_day.values() for p in plist]
    employees = roster.employees_from_punches(all_punches)
    working_by_day = {d: roster.working_emp_codes_for(d) for d in days}
    leave_by_day = roster.on_leave_emp_codes_for_range(start, end)
    # Reuse the weekly service — same row shape — then re-wrap as a
    # monthly response so the API stays self-documenting.
    week_result = build_employees_week(
        employees=employees,
        punches_by_day=punches_by_day,
        days=days,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        rule=roster.default_shift(),
        now=now,
        working_emp_codes_by_day=working_by_day,
        on_leave_emp_codes_by_day=leave_by_day,
    )
    return EmployeesMonthResponse(
        range_start=week_result.range_start,
        range_end=week_result.range_end,
        rows=week_result.rows,
    )


@router.get("/employees/range", response_model=EmployeesMonthResponse)
def employees_range(
    start: date = Query(...),
    end: date = Query(...),
    now: datetime = Depends(now_in_tz),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> EmployeesMonthResponse:
    """One row per employee with 1+ punches in an explicit [start, end] range.

    Same shape as /employees/month — reuses the same response model
    because the row contract is identical (employee + daily children).
    Drives the Employees tab when the dashboard's custom-range picker
    is active.

    Speed: one paginated Supabase query for the range. Odoo state
    reused from cache. Performance scales linearly with range size;
    a 30-day pick is ~5-6 pages, a 7-day pick is 1-2.
    """
    if start > end:
        # Auto-swap rather than 400, matches the dashboard route's
        # tolerance for reversed user picks.
        start, end = end, start
    # Defensive cap: anything beyond a quarter is almost certainly a
    # user mistake and risks slow Supabase queries.
    if (end - start).days > 95:
        raise HTTPException(
            status_code=400,
            detail="Range too large; max 95 days.",
        )
    days = iter_days(start, end)
    punches_by_day = repo.punches_grouped_by_day(start, end)
    all_punches = [p for plist in punches_by_day.values() for p in plist]
    employees = roster.employees_from_punches(all_punches)
    working_by_day = {d: roster.working_emp_codes_for(d) for d in days}
    leave_by_day = roster.on_leave_emp_codes_for_range(start, end)
    result = build_employees_week(
        employees=employees,
        punches_by_day=punches_by_day,
        days=days,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        rule=roster.default_shift(),
        now=now,
        working_emp_codes_by_day=working_by_day,
        on_leave_emp_codes_by_day=leave_by_day,
    )
    return EmployeesMonthResponse(
        range_start=result.range_start,
        range_end=result.range_end,
        rows=result.rows,
    )
