"""GET /api/employees/today — table of who punched in/out on a given day."""

from datetime import date

from fastapi import APIRouter, Depends

from app.api.deps import get_punch_repo, get_roster, parse_date
from app.infra.roster import RosterProvider
from app.infra.supabase_client import PunchRepository

from app.features.employees.models import EmployeesTodayResponse
from app.features.employees.service import build_employees_today

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
