"""Odoo-backed time-off lookups from the timesheet model.

One responsibility: tell the rest of the app which `emp_code`s were on
approved full-day leave on a given date, so the Employees views can show
those people as "On leave" instead of "Absent".

Source: `account.analytic.line` (the timesheet line model). A line counts
as full-day leave when:
  - its `task_id` display name is exactly "Time Off" (the approved-leave
    task Odoo posts against), and
  - its `unit_amount` (hours) is >= a full day (8h by default).

Matching to our roster: lines reference the employee via `employee_id`
(a many2one to hr.employee). We resolve that id back to our canonical
emp_code using the id→code map the employee repository already caches —
no name matching, no extra round-trip for the mapping.

Performance notes:
- Range-scoped, NOT TTL-cached: the query window changes per request, so
  caching by range buys little and risks staleness on same-day approvals.
  One paginated round-trip per Employees view request — same cost model as
  the Supabase punch fetch.
- The domain prunes server-side: date window + the Time-Off task name +
  the hours floor, so only relevant rows cross the wire.
- Result is `dict[date, frozenset[str]]` — O(1) per-day membership on the
  hot path in the service builders.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from typing import Mapping

from app.infra.odoo_calendars import _many2one_id
from app.infra.odoo_client import OdooClient
from app.infra.odoo_employees import _many2one_name

logger = logging.getLogger(__name__)

TIMESHEET_MODEL = "account.analytic.line"
EMPLOYEE_FIELD = "employee_id"
TASK_FIELD = "task_id"
DATE_FIELD = "date"
HOURS_FIELD = "unit_amount"

# The task name Odoo posts approved leave against. Matched case-sensitively
# to avoid sweeping in unrelated tasks that merely contain the phrase.
TIME_OFF_TASK = "Time Off"

# A timesheet line of this many hours (or more) on a Time-Off task counts
# as a full-day leave. Partial Time-Off entries stay "Absent" per the
# product decision (2026-05-31).
FULL_DAY_HOURS = 8.0


def _coerce_hours(raw: object) -> float:
    """Odoo returns unit_amount as float; tolerate ints/strings/False."""
    if raw is False or raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _coerce_date(raw: object) -> date | None:
    """Odoo returns the date field as 'YYYY-MM-DD'. Returns None if unusable."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


class OdooTimesheetRepository:
    """Reads full-day leave entries from Odoo's timesheet model.

    `on_leave_emp_codes_for_range(start, end, emp_code_by_odoo_id)` returns
    a `{date: frozenset[emp_code]}` map of who was on full-day leave each
    day in the inclusive range.
    """

    def __init__(
        self,
        client: OdooClient,
        *,
        batch_size: int = 500,
        full_day_hours: float = FULL_DAY_HOURS,
    ) -> None:
        self._client = client
        self._batch_size = batch_size
        self._full_day_hours = full_day_hours

    def on_leave_emp_codes_for_range(
        self,
        start: date,
        end: date,
        emp_code_by_odoo_id: Mapping[int, str],
    ) -> dict[date, frozenset[str]]:
        """Map each day in [start, end] to the emp_codes on full-day leave.

        Days with no leave are simply absent from the map (callers treat a
        missing day as "nobody on leave"). The hours floor is applied
        server-side via the domain AND re-checked here in case Odoo's
        numeric comparison rounds differently than ours.
        """
        domain = [
            (DATE_FIELD, ">=", start.isoformat()),
            (DATE_FIELD, "<=", end.isoformat()),
            (TASK_FIELD, "=", TIME_OFF_TASK),
            (HOURS_FIELD, ">=", self._full_day_hours),
        ]
        rows = self._client.search_read(
            TIMESHEET_MODEL,
            domain,
            [EMPLOYEE_FIELD, TASK_FIELD, DATE_FIELD, HOURS_FIELD],
            batch_size=self._batch_size,
        )

        by_day: dict[date, set[str]] = defaultdict(set)
        for row in rows:
            # Defensive: re-verify the task name and hours even though the
            # domain filters them — a misconfigured domain shouldn't leak
            # partial-day or non-leave lines into "On leave".
            if _many2one_name(row.get(TASK_FIELD)) != TIME_OFF_TASK:
                continue
            if _coerce_hours(row.get(HOURS_FIELD)) < self._full_day_hours:
                continue
            day = _coerce_date(row.get(DATE_FIELD))
            if day is None:
                continue
            odoo_id = _many2one_id(row.get(EMPLOYEE_FIELD))
            if odoo_id is None:
                continue
            code = emp_code_by_odoo_id.get(odoo_id)
            if code is None:
                # Timesheet references an employee not in our attendance
                # roster — not someone we track, skip.
                continue
            by_day[day].add(code)

        logger.info(
            "Odoo account.analytic.line → full-day leave on %d day(s) "
            "in %s..%s",
            len(by_day),
            start.isoformat(),
            end.isoformat(),
        )
        return {day: frozenset(codes) for day, codes in by_day.items()}
