"""Employees routes — daily and weekly views of attendance punches.

Both routes share the same Odoo state (cached) and the same punch
fetching primitives. Weekly costs one paginated Supabase round-trip;
daily costs one too. Zero extra Odoo calls in either path.
"""

from datetime import date

from fastapi import APIRouter, Depends

from app.api.deps import get_punch_repo, get_roster, parse_date
from app.infra.roster import RosterProvider
from app.infra.supabase_client import PunchRepository
from app.shared.date_range import iter_days, week_range_for

from app.features.employees.models import (
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
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> EmployeesTodayResponse:
    punches = repo.punches_for_day(day)
    employees = roster.employees_from_punches(punches)
    return build_employees_today(
        employees=employees,
        punches=punches,
        day=day,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
    )


@router.get("/employees/week", response_model=EmployeesWeekResponse)
def employees_week(
    day: date = Depends(parse_date),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> EmployeesWeekResponse:
    """One row per employee with 1+ punches in the Sun–Sat week of `day`.

    Single paginated Supabase query for the whole week. Aggregation
    happens in memory; Odoo state is reused from cache. The shift rule
    + per-day working sets feed the per-employee expected-hours total
    (excludes WFH days, so a Sun–Thu employee expects 4 × 8h = 32h).
    """
    start, end = week_range_for(day)
    days = iter_days(start, end)
    punches_by_day = repo.punches_grouped_by_day(start, end)
    all_punches = [p for plist in punches_by_day.values() for p in plist]
    employees = roster.employees_from_punches(all_punches)
    working_by_day = {d: roster.working_emp_codes_for(d) for d in days}
    return build_employees_week(
        employees=employees,
        punches_by_day=punches_by_day,
        days=days,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        rule=roster.default_shift(),
        working_emp_codes_by_day=working_by_day,
    )
