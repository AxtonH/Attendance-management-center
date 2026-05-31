"""Shared FastAPI dependencies.

These are the seams the rest of the API depends on. Tests override them via
`app.dependency_overrides[...]` to inject fakes — no monkeypatching needed.
"""

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, Query

from app.config import Settings, get_settings
from app.infra.odoo_calendars import OdooCalendarRepository
from app.infra.odoo_client import OdooClient
from app.infra.odoo_employees import OdooEmployeeRepository
from app.infra.odoo_timesheets import OdooTimesheetRepository
from app.infra.roster import (
    OdooRosterProvider,
    PunchDerivedRosterProvider,
    RosterProvider,
)
from app.infra.supabase_client import PunchRepository, build_supabase_client


@lru_cache
def _punch_derived_roster_singleton(config_dir: str) -> PunchDerivedRosterProvider:
    return PunchDerivedRosterProvider(Path(config_dir))


@lru_cache
def _odoo_roster_singleton(
    config_dir: str,
    url: str,
    db: str,
    username: str,
    password: str,
    cache_ttl: int,
    batch_size: int,
) -> OdooRosterProvider:
    # Singletons keyed by the full connection tuple so test overrides that
    # change credentials produce a fresh client instead of reusing a stale one.
    client = OdooClient(url=url, db=db, username=username, password=password)
    employees = OdooEmployeeRepository(
        client, cache_ttl_seconds=cache_ttl, batch_size=batch_size
    )
    calendars = OdooCalendarRepository(
        client, cache_ttl_seconds=cache_ttl, batch_size=batch_size
    )
    timesheets = OdooTimesheetRepository(client, batch_size=batch_size)
    fallback = _punch_derived_roster_singleton(config_dir)
    return OdooRosterProvider(
        odoo_employees=employees,
        odoo_calendars=calendars,
        fallback=fallback,
        odoo_timesheets=timesheets,
    )


def get_roster(settings: Settings = Depends(get_settings)) -> RosterProvider:
    config_dir = str(settings.resolved_config_dir)
    if settings.odoo_configured:
        return _odoo_roster_singleton(
            config_dir,
            settings.odoo_url,
            settings.odoo_db,
            settings.odoo_username,
            settings.odoo_password,
            settings.odoo_employee_cache_ttl,
            settings.odoo_batch_size,
        )
    return _punch_derived_roster_singleton(config_dir)


@lru_cache
def _repo_singleton(url: str, key: str) -> PunchRepository:
    return PunchRepository(build_supabase_client(url, key))


def get_punch_repo(settings: Settings = Depends(get_settings)) -> PunchRepository:
    return _repo_singleton(settings.supabase_url, settings.supabase_service_role_key)


def get_tz(settings: Settings = Depends(get_settings)) -> ZoneInfo:
    return ZoneInfo(settings.app_timezone)


def parse_date(
    date_str: str | None = Query(default=None, alias="date", description="YYYY-MM-DD"),
    tz: ZoneInfo = Depends(get_tz),
) -> date:
    if date_str is None:
        return datetime.now(tz).date()
    return date.fromisoformat(date_str)


def now_in_tz(tz: ZoneInfo = Depends(get_tz)) -> datetime:
    # Return naive datetime in the app timezone so it compares cleanly with
    # naive punch_time values from Supabase (TIMESTAMP without tz).
    return datetime.now(tz).replace(tzinfo=None)
