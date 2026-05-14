"""Odoo-backed employee lookups.

One responsibility: tell the rest of the app which `emp_code`s belong to
employees enrolled in the attendance system, what to call them, and which
resource calendar they're on.

Names come from `hr.employee.name` — that makes Odoo the single source of
truth for display, so BioTime/Odoo name drift disappears for the dashboard.

Performance notes:
- Three fields fetched (`x_studio_employee_code`, `name`,
  `resource_calendar_id`) — still tiny payload (~hundreds of rows).
- One round-trip serves the roster set, names, and calendar mapping.
- Pages of `batch_size` (default 500) keep the XML-RPC payloads bounded.
- Cached as a `dict[str, ...]`; `expected_emp_codes()` returns a derived
  `frozenset` view (free — just `.keys()`) so the dashboard hot path stays
  a pure set-difference.
- TTL refresh is opportunistic and single-flight: only one thread refills
  the cache when it expires; the others wait on the lock and read the
  fresh value.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from app.infra.odoo_calendars import _many2one_id
from app.infra.odoo_client import OdooClient

logger = logging.getLogger(__name__)

EMPLOYEE_MODEL = "hr.employee"
EMP_CODE_FIELD = "x_studio_employee_code"
NAME_FIELD = "name"
CALENDAR_FIELD = "resource_calendar_id"
DEPARTMENT_FIELD = "department_id"


def _normalize_emp_code(raw: object) -> str | None:
    """Coerce an Odoo emp_code value into a canonical string, or None to skip.

    Odoo can return the custom field as `False` (unset), an int, a string,
    or whitespace. Anything that resolves to '0' or empty means 'not in
    the attendance system' per the project rule.
    """
    if raw is False or raw is None:
        return None
    if isinstance(raw, int | float):
        code = str(int(raw))
    else:
        code = str(raw).strip()
    if not code or code == "0":
        return None
    return code


def _normalize_name(raw: object, fallback: str) -> str:
    """Coerce Odoo name to a clean string; fall back to emp_code if missing."""
    if raw is False or raw is None:
        return fallback
    name = str(raw).strip()
    return name or fallback


@dataclass(frozen=True)
class _CacheEntry:
    # MappingProxyType makes the dicts read-only for callers without copying.
    names: Mapping[str, str]
    codes: frozenset[str]
    # emp_code → Odoo calendar id (None when the employee has no calendar).
    calendar_ids: Mapping[str, int | None]
    # emp_code → department display name. "" when the employee has no
    # department set (shown as "Unassigned" in the rollup).
    departments: Mapping[str, str]
    fetched_at: float


class OdooEmployeeRepository:
    """Reads the attendance-enrolled employee roster from Odoo.

    Exposes three views over the same cached payload:
    - `expected_emp_codes()` → `frozenset[str]` for set-math (Present/Absent).
    - `display_names()` → `Mapping[str, str]` for name lookup in panels.
    - `calendar_ids()` → `Mapping[str, int | None]` for working-day lookup.
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

    def expected_emp_codes(self) -> frozenset[str]:
        return self._get_cache().codes

    def display_names(self) -> Mapping[str, str]:
        return self._get_cache().names

    def calendar_ids(self) -> Mapping[str, int | None]:
        return self._get_cache().calendar_ids

    def departments(self) -> Mapping[str, str]:
        return self._get_cache().departments

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
        # Domain prunes obvious non-attendance rows server-side. The
        # `!=` filters cover Odoo's "false" representation for empty
        # custom fields as well as literal 0 in both string and int form.
        domain = [
            ("active", "=", True),
            (EMP_CODE_FIELD, "!=", False),
            (EMP_CODE_FIELD, "!=", ""),
            (EMP_CODE_FIELD, "!=", "0"),
            (EMP_CODE_FIELD, "!=", 0),
        ]
        rows = self._client.search_read(
            EMPLOYEE_MODEL,
            domain,
            [EMP_CODE_FIELD, NAME_FIELD, CALENDAR_FIELD, DEPARTMENT_FIELD],
            batch_size=self._batch_size,
        )
        names: dict[str, str] = {}
        calendars: dict[str, int | None] = {}
        departments: dict[str, str] = {}
        for row in rows:
            code = _normalize_emp_code(row.get(EMP_CODE_FIELD))
            if code is None:
                continue
            names[code] = _normalize_name(row.get(NAME_FIELD), code)
            calendars[code] = _many2one_id(row.get(CALENDAR_FIELD))
            departments[code] = _many2one_name(row.get(DEPARTMENT_FIELD))
        logger.info("Odoo hr.employee → %d attendance-enrolled employees", len(names))
        return _CacheEntry(
            names=MappingProxyType(names),
            codes=frozenset(names.keys()),
            calendar_ids=MappingProxyType(calendars),
            departments=MappingProxyType(departments),
            fetched_at=time.monotonic(),
        )


def _many2one_name(value: object) -> str:
    """Extract the display name from an Odoo many2one return shape.

    XML-RPC returns many2one as `[id, "Display Name"]` or `False` when unset.
    Returns "" for unset — the rollup treats that as "Unassigned".
    """
    if isinstance(value, list) and len(value) >= 2:
        return str(value[1] or "").strip()
    return ""
