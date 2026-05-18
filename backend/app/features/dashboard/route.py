"""Dashboard routes.

`/api/dashboard` is the canonical single-call endpoint the dashboard page hits.
The four sub-panel endpoints (`/overview`, `/exceptions`, `/arrivals/histogram`,
`/departments/rollup`) stay for ad-hoc fetches and debugging — they all hit
the same domain functions, so there's no logic duplication.
"""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_punch_repo, get_roster, now_in_tz, parse_date
from app.infra.roster import RosterProvider
from app.infra.supabase_client import PunchRepository

from app.features.dashboard.models import (
    ArrivalsResponse,
    DashboardResponse,
    DepartmentsResponse,
    ExceptionsResponse,
    OverviewResponse,
)
from app.features.dashboard.service import (
    build_arrivals,
    build_dashboard,
    build_departments_placeholder,
    build_departments_rollup,
    build_exceptions,
    build_overview,
)
from app.features.dashboard.weekly import build_weekly_dashboard
from app.shared.date_range import iter_days, month_range_for, week_range_for

router = APIRouter(tags=["dashboard"])

FilterType = Literal[
    "all", "late", "absent", "missing_punch", "incomplete_hours", "review"
]

Mode = Literal["daily", "weekly", "monthly"]


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    day: date = Depends(parse_date),
    now: datetime = Depends(now_in_tz),
    mode: Mode = Query(default="daily"),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> DashboardResponse:
    if mode == "monthly":
        return _build_range(day, now, roster, repo, kind="monthly")
    if mode == "weekly":
        return _build_range(day, now, roster, repo, kind="weekly")
    return _build_daily(day, now, roster, repo)


def _build_daily(
    day: date,
    now: datetime,
    roster: RosterProvider,
    repo: PunchRepository,
) -> DashboardResponse:
    punches = repo.punches_for_day(day)
    prev_day, prev_punches = repo.punches_for_previous_working_day(day)
    employees = roster.employees_from_punches(punches)
    working_today = roster.working_emp_codes_for(day)
    working_prev = (
        roster.working_emp_codes_for(prev_day) if prev_day is not None else None
    )
    return build_dashboard(
        employees=employees,
        punches=punches,
        rule=roster.default_shift(),
        day=day,
        now=now,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        working_emp_codes=working_today,
        working_emp_codes_prev_day=working_prev,
        department_by_emp_code=roster.department_by_emp_code(),
        prev_working_day=prev_day,
        prev_working_day_punches=prev_punches,
    )


def _build_range(
    day: date,
    now: datetime,
    roster: RosterProvider,
    repo: PunchRepository,
    *,
    kind: Literal["weekly", "monthly"],
) -> DashboardResponse:
    """Unified multi-day builder. Weekly and monthly share aggregators —
    only the date range, the response's mode label, and the exception
    chip strategy differ.

    Performance: one paginated Supabase round-trip for the whole range.
    Odoo state is reused from cache. A month query is ~5-6 pages, a week
    is 1-2; both are well under a second on typical Prezlab data.
    """
    if kind == "monthly":
        start, end = month_range_for(day)
    else:
        start, end = week_range_for(day)
    days = iter_days(start, end)

    punches_by_day = repo.punches_grouped_by_day(start, end)

    # The aggregator wants `employees` for name/department lookups when
    # the Odoo roster doesn't have a code — flatten all punches so the
    # punch-derived list covers everyone who appeared at least once.
    all_punches = [p for plist in punches_by_day.values() for p in plist]
    employees = roster.employees_from_punches(all_punches)

    working_by_day = {d: roster.working_emp_codes_for(d) for d in days}

    # Monthly: drop day chips on exception rows (a chronic offender
    # could have 20+ days). The detail line absorbs the count instead.
    show_day_chips = kind == "weekly"

    return build_weekly_dashboard(
        employees=employees,
        punches_by_day=punches_by_day,
        rule=roster.default_shift(),
        days=days,
        now=now,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        department_by_emp_code=roster.department_by_emp_code(),
        working_emp_codes_by_day=working_by_day,
        mode_label=kind,
        show_day_chips=show_day_chips,
    )


@router.get("/overview", response_model=OverviewResponse)
def overview(
    day: date = Depends(parse_date),
    now: datetime = Depends(now_in_tz),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> OverviewResponse:
    punches = repo.punches_for_day(day)
    employees = roster.employees_from_punches(punches)
    return build_overview(
        employees,
        punches,
        roster.default_shift(),
        day,
        now,
        expected_emp_codes=roster.expected_emp_codes(),
        working_emp_codes=roster.working_emp_codes_for(day),
    )


@router.get("/exceptions", response_model=ExceptionsResponse)
def exceptions(
    day: date = Depends(parse_date),
    now: datetime = Depends(now_in_tz),
    filter: FilterType = Query(default="all"),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> ExceptionsResponse:
    punches = repo.punches_for_day(day)
    prev_day, prev_punches = repo.punches_for_previous_working_day(day)
    employees = roster.employees_from_punches(punches)
    working_today = roster.working_emp_codes_for(day)
    working_prev = (
        roster.working_emp_codes_for(prev_day) if prev_day is not None else None
    )
    return build_exceptions(
        employees,
        punches,
        roster.default_shift(),
        day,
        now,
        filter_type=filter,
        expected_emp_codes=roster.expected_emp_codes(),
        roster_names=roster.display_names(),
        working_emp_codes=working_today,
        working_emp_codes_prev_day=working_prev,
        prev_working_day=prev_day,
        prev_working_day_punches=prev_punches,
    )


@router.get("/departments/rollup", response_model=DepartmentsResponse)
def departments_rollup(
    day: date = Depends(parse_date),
    now: datetime = Depends(now_in_tz),
    roster: RosterProvider = Depends(get_roster),
    repo: PunchRepository = Depends(get_punch_repo),
) -> DepartmentsResponse:
    dept_map = roster.department_by_emp_code()
    if not dept_map:
        # Phase-1 mode or Odoo not configured → keep returning the placeholder.
        return build_departments_placeholder(day)
    punches = repo.punches_for_day(day)
    return build_departments_rollup(
        punches=punches,
        rule=roster.default_shift(),
        day=day,
        now=now,
        department_by_emp_code=dept_map,
        expected_emp_codes=roster.expected_emp_codes(),
        working_emp_codes=roster.working_emp_codes_for(day),
    )


@router.get("/arrivals/histogram", response_model=ArrivalsResponse)
def arrivals_histogram(
    day: date = Depends(parse_date),
    bucket_minutes: int = Query(default=30, ge=5, le=120),
    window_start: str = Query(default="08:00"),
    window_end: str = Query(default="10:00"),
    repo: PunchRepository = Depends(get_punch_repo),
) -> ArrivalsResponse:
    punches = repo.punches_for_day(day)
    return build_arrivals(
        punches=punches,
        day=day,
        bucket_minutes=bucket_minutes,
        window_start=window_start,
        window_end=window_end,
    )
