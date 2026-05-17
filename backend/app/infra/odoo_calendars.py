"""Resolve Odoo resource calendars to sets of working weekdays.

Two-tier resolution per design decision (2026-05-14):
  1. Structured: read `resource.calendar.attendance.dayofweek` rows — the
     real working-hours table that the display name labels.
  2. Fallback: parse the calendar's `display_name` string (see
     `calendar_parser.parse_working_days`).

If both fail (empty attendance rows AND unparseable name), we fail OPEN —
every day is a working day. That over-flags weekends rather than silently
missing real absences on workdays.

Caching: same TTL window as OdooEmployeeRepository. The calendar list is
small and stable (a handful of rows), so we fetch the whole world each
refresh — far cheaper than per-employee lookups.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from app.infra.calendar_parser import PREZLAB_DEFAULT_DAYS, parse_working_days
from app.infra.odoo_client import OdooClient

logger = logging.getLogger(__name__)

CALENDAR_MODEL = "resource.calendar"
ATTENDANCE_MODEL = "resource.calendar.attendance"
NAME_FIELD = "name"
DAYOFWEEK_FIELD = "dayofweek"
CALENDAR_ID_FIELD = "calendar_id"


@dataclass(frozen=True)
class _CacheEntry:
    # calendar_id → frozenset of weekdays (Mon=0..Sun=6).
    days_by_calendar: Mapping[int, frozenset[int]]
    fetched_at: float


class OdooCalendarRepository:
    """Working-day lookup keyed by calendar id.

    The `working_days_for_calendar(calendar_id)` hot path is a dict get,
    O(1) per call. Population happens once per TTL window, in one
    Odoo round-trip per Odoo model touched (two total).
    """

    def __init__(
        self,
        client: OdooClient,
        *,
        cache_ttl_seconds: int = 300,
        batch_size: int = 500,
    ) -> None:
        self._client = client
        self._cache_ttl = cache_ttl_seconds
        self._batch_size = batch_size
        self._cache: _CacheEntry | None = None
        self._lock = threading.Lock()

    def working_days_for_calendar(self, calendar_id: int | None) -> frozenset[int]:
        """Set of working weekdays for the given calendar id.

        Unknown calendar ids fall back to the Prezlab default (Sun–Thu)
        rather than all-7-days. Originally this was fail-OPEN to avoid
        missing real absences, but in practice it caused the opposite
        problem: people who came into the office on their day off were
        getting flagged for incomplete-hours/missing-punch because the
        defaulted calendar said Saturday was a workday. Prezlab default
        is the right neutral assumption — covers the standard 90% case.
        """
        if calendar_id is None:
            return PREZLAB_DEFAULT_DAYS
        return self._get_cache().days_by_calendar.get(
            calendar_id, PREZLAB_DEFAULT_DAYS
        )

    def invalidate(self) -> None:
        with self._lock:
            self._cache = None

    def _get_cache(self) -> _CacheEntry:
        now = time.monotonic()
        cache = self._cache
        if cache is not None and (now - cache.fetched_at) < self._cache_ttl:
            return cache

        with self._lock:
            cache = self._cache
            now = time.monotonic()
            if cache is not None and (now - cache.fetched_at) < self._cache_ttl:
                return cache
            cache = self._fetch()
            self._cache = cache
            return cache

    def _fetch(self) -> _CacheEntry:
        # active_test=False is critical here. Odoo applies an implicit
        # `active=True` filter to any model with an `active` field, so
        # without this we silently drop archived calendars — and employees
        # CAN still be assigned to archived calendars (we saw exactly this
        # cause Nour to get flagged on Saturday: his calendar id 4 was
        # archived in Odoo, so it wasn't in our cache, so the lookup fell
        # through to the all-days fallback and Saturday became a workday).
        include_archived = {"active_test": False}

        calendars = self._client.search_read(
            CALENDAR_MODEL,
            [],
            ["id", NAME_FIELD],
            batch_size=self._batch_size,
            context=include_archived,
        )
        names_by_id: dict[int, str] = {
            row["id"]: str(row.get(NAME_FIELD) or "") for row in calendars
        }

        # Read attendance rows (structured working-hour table). Odoo stores
        # `dayofweek` as a string ("0".."6"), with Monday=0. Same
        # active_test=False — attendance rows can also be archived (and
        # are auto-archived when their parent calendar is).
        attendance_rows = self._client.search_read(
            ATTENDANCE_MODEL,
            [],
            [CALENDAR_ID_FIELD, DAYOFWEEK_FIELD],
            batch_size=self._batch_size,
            context=include_archived,
        )
        structured: dict[int, set[int]] = {}
        for row in attendance_rows:
            cal_ref = row.get(CALENDAR_ID_FIELD)
            cal_id = _many2one_id(cal_ref)
            if cal_id is None:
                continue
            dow = _coerce_dayofweek(row.get(DAYOFWEEK_FIELD))
            if dow is None:
                continue
            structured.setdefault(cal_id, set()).add(dow)

        # Compose: tier 1 wins; tier 2 (parse name) covers calendars with
        # no attendance rows.
        days_by_calendar: dict[int, frozenset[int]] = {}
        for cal_id, name in names_by_id.items():
            if cal_id in structured and structured[cal_id]:
                days_by_calendar[cal_id] = frozenset(structured[cal_id])
            else:
                days_by_calendar[cal_id] = parse_working_days(name)

        logger.info(
            "Odoo resource.calendar → %d calendars resolved "
            "(structured=%d, parsed=%d)",
            len(days_by_calendar),
            sum(1 for c in names_by_id if c in structured and structured[c]),
            sum(1 for c in names_by_id if c not in structured or not structured[c]),
        )
        return _CacheEntry(
            days_by_calendar=MappingProxyType(days_by_calendar),
            fetched_at=time.monotonic(),
        )


def _many2one_id(value: object) -> int | None:
    """Extract an id from an Odoo many2one return shape.

    XML-RPC returns many2one fields as `[id, "Display Name"]` or `False`
    when unset. Sometimes scripts may write an int directly — handle both.
    """
    if value is False or value is None:
        return None
    if isinstance(value, list) and value and isinstance(value[0], int):
        return value[0]
    if isinstance(value, int):
        return value
    return None


def _coerce_dayofweek(value: object) -> int | None:
    """Odoo stores dayofweek as a stringified int '0'..'6'. Accept ints too."""
    if value is False or value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= n <= 6:
        return n
    return None


def calendar_ids_in_use(
    calendar_refs: Iterable[object],
) -> frozenset[int]:
    """Helper: extract a unique id set from a stream of many2one refs."""
    out: set[int] = set()
    for ref in calendar_refs:
        cid = _many2one_id(ref)
        if cid is not None:
            out.add(cid)
    return frozenset(out)
