"""Tests for OdooCalendarRepository's two-tier resolution.

Structured attendance rows win over name parsing; name parsing kicks in
only when a calendar has no attendance rows.
"""

from __future__ import annotations

from typing import Any

from app.infra.calendar_parser import PREZLAB_DEFAULT_DAYS
from app.infra.odoo_calendars import (
    ATTENDANCE_MODEL,
    CALENDAR_ID_FIELD,
    CALENDAR_MODEL,
    DAYOFWEEK_FIELD,
    NAME_FIELD,
    OdooCalendarRepository,
)
from app.infra.odoo_client import OdooClient


class FakeOdooClient(OdooClient):
    """Returns different canned rows per model. Bypasses XML-RPC entirely.

    Honors `active_test=False` exactly like real Odoo: rows are filtered
    out by an implicit `active=True` check UNLESS the caller passes
    `context={"active_test": False}`. Lets us regression-test the
    "Nour archived-calendar" bug.
    """

    def __init__(
        self,
        calendar_rows: list[dict[str, Any]],
        attendance_rows: list[dict[str, Any]],
    ) -> None:
        self._calendar_rows = calendar_rows
        self._attendance_rows = attendance_rows
        self.call_count = 0
        self.last_context: dict[str, Any] | None = None

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        batch_size: int = 500,
        order: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.call_count += 1
        self.last_context = context
        if model == CALENDAR_MODEL:
            rows = self._calendar_rows
        elif model == ATTENDANCE_MODEL:
            rows = self._attendance_rows
        else:
            rows = []
        # Mimic Odoo's implicit active-test filter.
        active_test = not (context and context.get("active_test") is False)
        if active_test:
            rows = [r for r in rows if r.get("active", True)]
        return [{k: r.get(k) for k in fields} for r in rows]


class TestStructuredWinsOverName:
    def test_attendance_rows_take_precedence(self):
        # Calendar 1 has structured rows {Mon, Wed, Thu}; its name says Sun-Thu.
        # Structured must win.
        client = FakeOdooClient(
            calendar_rows=[{"id": 1, NAME_FIELD: "JO & KSA | Sun - Thu | Day Shift"}],
            attendance_rows=[
                {CALENDAR_ID_FIELD: [1, "..."], DAYOFWEEK_FIELD: "0"},  # Mon
                {CALENDAR_ID_FIELD: [1, "..."], DAYOFWEEK_FIELD: "2"},  # Wed
                {CALENDAR_ID_FIELD: [1, "..."], DAYOFWEEK_FIELD: "3"},  # Thu
            ],
        )
        repo = OdooCalendarRepository(client, cache_ttl_seconds=60)
        assert repo.working_days_for_calendar(1) == frozenset({0, 2, 3})

    def test_falls_back_to_parsing_when_no_attendance_rows(self):
        client = FakeOdooClient(
            calendar_rows=[{"id": 2, NAME_FIELD: "JO & KSA | Mon - Fri | Day Shift A"}],
            attendance_rows=[],
        )
        repo = OdooCalendarRepository(client, cache_ttl_seconds=60)
        assert repo.working_days_for_calendar(2) == frozenset({0, 1, 2, 3, 4})

    def test_falls_back_to_default_when_name_unparseable_and_no_rows(self):
        client = FakeOdooClient(
            calendar_rows=[{"id": 3, NAME_FIELD: "Some Custom Schedule"}],
            attendance_rows=[],
        )
        repo = OdooCalendarRepository(client, cache_ttl_seconds=60)
        assert repo.working_days_for_calendar(3) == PREZLAB_DEFAULT_DAYS


class TestInactiveCalendars:
    """Regression: employees can be assigned to ARCHIVED calendars in Odoo.

    If we don't pass `active_test=False`, those calendars are silently
    invisible to our cache, the lookup falls through to a default, and
    employees may get falsely flagged on what's actually their day off.
    Real-world example (2026-05-17): Nour was on archived 'Standard 40
    hours/week' id 4, which was Mon–Fri; cache fell through to PREZLAB
    default (Sun–Thu); Saturday wasn't a workday for either schedule so
    the symptom didn't show — but if his real calendar had been e.g.
    Tue–Sat, he'd have been silently un-flagged on Tuesdays. Either way,
    the cache should match Odoo, not a guess.
    """

    def test_archived_calendars_included_in_cache(self):
        client = FakeOdooClient(
            calendar_rows=[
                {
                    "id": 4,
                    NAME_FIELD: "Standard 40 hours/week",
                    "active": False,  # archived
                },
            ],
            attendance_rows=[
                {CALENDAR_ID_FIELD: [4, "..."], DAYOFWEEK_FIELD: "0", "active": False},
                {CALENDAR_ID_FIELD: [4, "..."], DAYOFWEEK_FIELD: "1", "active": False},
                {CALENDAR_ID_FIELD: [4, "..."], DAYOFWEEK_FIELD: "2", "active": False},
                {CALENDAR_ID_FIELD: [4, "..."], DAYOFWEEK_FIELD: "3", "active": False},
                {CALENDAR_ID_FIELD: [4, "..."], DAYOFWEEK_FIELD: "4", "active": False},
            ],
        )
        repo = OdooCalendarRepository(client, cache_ttl_seconds=60)
        # The archived calendar must resolve from its OWN data (Mon–Fri),
        # not from the Prezlab default.
        assert repo.working_days_for_calendar(4) == frozenset({0, 1, 2, 3, 4})

    def test_active_test_false_is_passed_in_context(self):
        client = FakeOdooClient(calendar_rows=[], attendance_rows=[])
        repo = OdooCalendarRepository(client, cache_ttl_seconds=60)
        repo.working_days_for_calendar(1)  # triggers _fetch
        assert client.last_context is not None
        assert client.last_context.get("active_test") is False


class TestCache:
    def test_one_fetch_per_ttl_window(self):
        client = FakeOdooClient(
            calendar_rows=[{"id": 1, NAME_FIELD: "X"}],
            attendance_rows=[],
        )
        repo = OdooCalendarRepository(client, cache_ttl_seconds=300)
        repo.working_days_for_calendar(1)
        repo.working_days_for_calendar(1)
        repo.working_days_for_calendar(1)
        # 2 calls: one for resource.calendar, one for attendance. Both happen
        # exactly once thanks to the single cached _CacheEntry.
        assert client.call_count == 2

    def test_invalidate_forces_refetch(self):
        client = FakeOdooClient(
            calendar_rows=[{"id": 1, NAME_FIELD: "X"}],
            attendance_rows=[],
        )
        repo = OdooCalendarRepository(client, cache_ttl_seconds=300)
        repo.working_days_for_calendar(1)
        repo.invalidate()
        repo.working_days_for_calendar(1)
        assert client.call_count == 4
