"""Odoo-backed public-holiday lookups from the calendar-leaves model.

One responsibility: tell the rest of the app which Odoo *companies* have a
company-wide public holiday on a given date, so the Employees views can
show an affected employee as "Holiday" instead of "Absent".

Source: `resource.calendar.leaves`. This model holds two kinds of rows:
  - company-wide public holidays — no `resource_id` (applies to everyone
    in `company_id`), and
  - individual time-off allocations — a specific `resource_id`.
We only consume the FIRST kind here. Individual leave is handled by the
Time-Off timesheet path (`odoo_timesheets`), so a row with a `resource_id`
is ignored to avoid double-counting.

Matching to employees happens one layer up (the roster provider): a
holiday for company X applies to every employee whose `company_id` is X.
Keeping the company→employee expansion out of this module means the repo
stays a pure "what's closed for which company, when" lookup.

Performance notes:
- Range-scoped, NOT TTL-cached: the query window changes per request.
  One paginated round-trip per dashboard/Employees request. Holiday rows
  are few (a handful per company per year), so the payload is tiny.
- The domain prunes server-side: the date window (overlapping the range)
  plus `resource_id = False` so individual leave never crosses the wire.
- Result is `dict[date, frozenset[int]]` (day → company ids) — O(1)
  per-day membership for the caller.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.infra.odoo_calendars import _many2one_id
from app.infra.odoo_client import OdooClient

logger = logging.getLogger(__name__)

HOLIDAY_MODEL = "resource.calendar.leaves"
COMPANY_FIELD = "company_id"
RESOURCE_FIELD = "resource_id"
DATE_FROM_FIELD = "date_from"
DATE_TO_FIELD = "date_to"


def _coerce_local_date(raw: object, tz: ZoneInfo) -> date | None:
    """Convert an Odoo `date_from`/`date_to` value to a local calendar day.

    `resource.calendar.leaves.date_from`/`date_to` are Datetime fields,
    which Odoo stores in UTC and the XML-RPC API returns in UTC (our API
    user carries no timezone). A holiday meant for 25 May in Asia/Amman
    (UTC+3) comes back as '2026-05-24 21:00:00' — so naively slicing the
    first 10 chars lands it on the 24th. We must interpret the value as
    UTC and convert to the app timezone before taking the date.

    Accepts:
      - 'YYYY-MM-DD HH:MM:SS' → parsed as UTC, converted to `tz`.
      - 'YYYY-MM-DD' (date-only, no tz meaning) → returned as-is.
    Returns None if unusable.
    """
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    # Date-only value: no time component, so no timezone shift applies.
    if len(text) == 10:
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    try:
        naive = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    # Odoo datetimes are UTC; convert to the app timezone, then take the day.
    return naive.replace(tzinfo=timezone.utc).astimezone(tz).date()


class OdooHolidayRepository:
    """Reads company-wide public holidays from resource.calendar.leaves.

    `holiday_company_ids_for_range(start, end)` returns a
    `{date: frozenset[company_id]}` map: which companies are closed each
    day in the inclusive range.
    """

    def __init__(
        self,
        client: OdooClient,
        *,
        batch_size: int = 500,
        tz: ZoneInfo | None = None,
    ) -> None:
        self._client = client
        self._batch_size = batch_size
        # App timezone used to convert Odoo's UTC datetimes to local days.
        # Defaults to UTC (no shift) so tests and UTC deployments are safe.
        self._tz = tz or ZoneInfo("UTC")

    def holiday_company_ids_for_range(
        self, start: date, end: date
    ) -> dict[date, frozenset[int]]:
        """Map each day in [start, end] to the company ids on holiday.

        A holiday entry spans [date_from, date_to]; we clip it to the query
        range and mark every day in the overlap. Days with no holiday are
        absent from the map (caller treats missing as "no holiday").

        Odoo returns the span endpoints in UTC, so we convert each to the
        app timezone before deriving local calendar days (see
        `_coerce_local_date`).
        """
        # Overlap test: entry.date_from <= range_end AND entry.date_to >=
        # range_start. resource_id = False keeps this to company-wide
        # holidays, not individual leave stored on the same model.
        #
        # The window is padded by a day on each edge because the stored
        # values are UTC: a holiday on the local range boundary can sit up
        # to a full day outside the naive [start, end] strings (UTC±14h max).
        # The exact day-marking below, after tz conversion, keeps the result
        # precise — the pad only widens what we fetch.
        fetch_from = (start - timedelta(days=1)).isoformat() + " 00:00:00"
        fetch_to = (end + timedelta(days=1)).isoformat() + " 23:59:59"
        domain = [
            (RESOURCE_FIELD, "=", False),
            (DATE_FROM_FIELD, "<=", fetch_to),
            (DATE_TO_FIELD, ">=", fetch_from),
        ]
        rows = self._client.search_read(
            HOLIDAY_MODEL,
            domain,
            [COMPANY_FIELD, RESOURCE_FIELD, DATE_FROM_FIELD, DATE_TO_FIELD],
            batch_size=self._batch_size,
        )

        by_day: dict[date, set[int]] = defaultdict(set)
        for row in rows:
            # Defensive: re-verify it's company-wide even though the domain
            # filters it — a misconfigured domain shouldn't leak personal
            # leave (which has a resource_id) into the holiday set.
            if _many2one_id(row.get(RESOURCE_FIELD)) is not None:
                continue
            company_id = _many2one_id(row.get(COMPANY_FIELD))
            if company_id is None:
                continue
            d_from = _coerce_local_date(row.get(DATE_FROM_FIELD), self._tz)
            d_to = _coerce_local_date(row.get(DATE_TO_FIELD), self._tz)
            if d_from is None or d_to is None or d_to < d_from:
                continue
            # Clip the entry span to the requested range, then mark days.
            span_start = max(d_from, start)
            span_end = min(d_to, end)
            cursor = span_start
            while cursor <= span_end:
                by_day[cursor].add(company_id)
                cursor += timedelta(days=1)

        logger.info(
            "Odoo resource.calendar.leaves → company-wide holidays on "
            "%d day(s) in %s..%s",
            len(by_day),
            start.isoformat(),
            end.isoformat(),
        )
        return {day: frozenset(ids) for day, ids in by_day.items()}
