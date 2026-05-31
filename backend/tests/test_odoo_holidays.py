"""Tests for the Odoo public-holiday repository.

Faked end-to-end via a stub OdooClient — no network. We exercise:
  1. Mapping resource.calendar.leaves rows → {date: {company_id}}.
  2. The company-wide filter (resource_id must be empty).
  3. Multi-day spans and clipping to the requested range.
  4. The domain used to prune server-side.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from app.infra.odoo_client import OdooClient
from app.infra.odoo_holidays import OdooHolidayRepository

AMMAN = ZoneInfo("Asia/Amman")  # UTC+3, no DST in 2026

START = date(2026, 5, 10)
END = date(2026, 5, 16)


def _holiday(
    company_id: int,
    date_from: str,
    date_to: str,
    resource: Any = False,
) -> dict[str, Any]:
    """Build a resource.calendar.leaves row in Odoo's XML-RPC shape."""
    return {
        "company_id": [company_id, f"Company {company_id}"],
        "resource_id": resource,
        "date_from": date_from,
        "date_to": date_to,
    }


class FakeOdooClient(OdooClient):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.last_domain: list[Any] | None = None
        self.call_count = 0

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
        self.last_domain = domain
        return list(self._rows)


class TestHolidayMapping:
    def test_single_day_holiday(self):
        rows = [_holiday(7, "2026-05-12 00:00:00", "2026-05-12 23:59:59")]
        repo = OdooHolidayRepository(FakeOdooClient(rows))
        result = repo.holiday_company_ids_for_range(START, END)
        assert result == {date(2026, 5, 12): frozenset({7})}

    def test_multi_day_span_marks_every_day(self):
        # A 3-day Eid holiday for company 7.
        rows = [_holiday(7, "2026-05-12 00:00:00", "2026-05-14 23:59:59")]
        repo = OdooHolidayRepository(FakeOdooClient(rows))
        result = repo.holiday_company_ids_for_range(START, END)
        assert set(result) == {
            date(2026, 5, 12),
            date(2026, 5, 13),
            date(2026, 5, 14),
        }
        assert all(v == frozenset({7}) for v in result.values())

    def test_span_clipped_to_query_range(self):
        # Holiday runs 05-08 .. 05-12 but query starts 05-10 → only the
        # 10, 11, 12 portion is reported.
        rows = [_holiday(7, "2026-05-08 00:00:00", "2026-05-12 23:59:59")]
        repo = OdooHolidayRepository(FakeOdooClient(rows))
        result = repo.holiday_company_ids_for_range(START, END)
        assert set(result) == {
            date(2026, 5, 10),
            date(2026, 5, 11),
            date(2026, 5, 12),
        }

    def test_two_companies_same_day(self):
        rows = [
            _holiday(7, "2026-05-12 00:00:00", "2026-05-12 23:59:59"),
            _holiday(8, "2026-05-12 00:00:00", "2026-05-12 23:59:59"),
        ]
        repo = OdooHolidayRepository(FakeOdooClient(rows))
        result = repo.holiday_company_ids_for_range(START, END)
        assert result == {date(2026, 5, 12): frozenset({7, 8})}

    def test_individual_leave_with_resource_excluded(self):
        # A row with a resource_id is personal leave, not a public holiday.
        rows = [
            _holiday(7, "2026-05-12 00:00:00", "2026-05-12 23:59:59", resource=[3, "Bob"]),
        ]
        repo = OdooHolidayRepository(FakeOdooClient(rows))
        result = repo.holiday_company_ids_for_range(START, END)
        assert result == {}

    def test_domain_filters_resource_and_date_overlap(self):
        client = FakeOdooClient([])
        repo = OdooHolidayRepository(client)
        repo.holiday_company_ids_for_range(START, END)
        domain = client.last_domain or []
        assert ("resource_id", "=", False) in domain
        # Overlap test edges present.
        assert any(d[0] == "date_from" and d[1] == "<=" for d in domain)
        assert any(d[0] == "date_to" and d[1] == ">=" for d in domain)


class TestTimezoneConversion:
    """Odoo stores date_from/date_to in UTC; with a UTC+3 app timezone the
    stored value for a 25-May holiday is '2026-05-24 21:00:00'..'2026-05-25
    20:59:59'. Converting to Asia/Amman must yield the 25th, not the 24th
    (the bug this fixes)."""

    def test_utc_stored_holiday_maps_to_local_day(self):
        # 25 May (Amman) holiday as Odoo stores it in UTC.
        rows = [_holiday(7, "2026-05-24 21:00:00", "2026-05-25 20:59:59")]
        repo = OdooHolidayRepository(FakeOdooClient(rows), tz=AMMAN)
        result = repo.holiday_company_ids_for_range(date(2026, 5, 20), date(2026, 5, 31))
        # Exactly the 25th — NOT the 24th.
        assert result == {date(2026, 5, 25): frozenset({7})}

    def test_without_tz_conversion_would_be_off_by_one(self):
        # Same row, default UTC tz (no conversion) reproduces the old bug:
        # the span starts on the 24th. This guards the regression — it
        # documents that the tz argument is what fixes it.
        rows = [_holiday(7, "2026-05-24 21:00:00", "2026-05-25 20:59:59")]
        repo = OdooHolidayRepository(FakeOdooClient(rows))  # tz defaults to UTC
        result = repo.holiday_company_ids_for_range(date(2026, 5, 20), date(2026, 5, 31))
        assert date(2026, 5, 24) in result  # the off-by-one, by design

    def test_date_only_value_not_shifted(self):
        # A pure date (no time) has no tz meaning; leave it as-is even with
        # a non-UTC app timezone.
        rows = [_holiday(7, "2026-05-25", "2026-05-25")]
        repo = OdooHolidayRepository(FakeOdooClient(rows), tz=AMMAN)
        result = repo.holiday_company_ids_for_range(date(2026, 5, 20), date(2026, 5, 31))
        assert result == {date(2026, 5, 25): frozenset({7})}

    def test_multi_day_utc_span_maps_to_local_days(self):
        # 3-day holiday 25-27 May (Amman), stored UTC.
        rows = [_holiday(7, "2026-05-24 21:00:00", "2026-05-27 20:59:59")]
        repo = OdooHolidayRepository(FakeOdooClient(rows), tz=AMMAN)
        result = repo.holiday_company_ids_for_range(date(2026, 5, 20), date(2026, 5, 31))
        assert set(result) == {
            date(2026, 5, 25),
            date(2026, 5, 26),
            date(2026, 5, 27),
        }
