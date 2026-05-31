"""OdooRosterProvider expands company-wide holidays to emp_codes.

The holiday repo reports closures by *company id*; the roster provider must
fan those out to every roster emp_code in that company, using the cached
emp_code → company_id map. These tests fake both collaborators so no Odoo
or network is involved.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping

from app.infra.roster import OdooRosterProvider, PunchDerivedRosterProvider

START = date(2026, 5, 10)
END = date(2026, 5, 16)
HOLIDAY = date(2026, 5, 12)


class _FakeEmployees:
    """Stands in for OdooEmployeeRepository: only company_ids() is used."""

    def __init__(self, company_ids: Mapping[str, int | None]) -> None:
        self._company_ids = company_ids

    def company_ids(self) -> Mapping[str, int | None]:
        return self._company_ids


class _FakeHolidays:
    """Stands in for OdooHolidayRepository."""

    def __init__(self, by_day: dict[date, frozenset[int]]) -> None:
        self._by_day = by_day

    def holiday_company_ids_for_range(
        self, start: date, end: date
    ) -> dict[date, frozenset[int]]:
        return self._by_day


def _provider(
    company_ids: Mapping[str, int | None],
    holidays: dict[date, frozenset[int]],
) -> OdooRosterProvider:
    return OdooRosterProvider(
        odoo_employees=_FakeEmployees(company_ids),  # type: ignore[arg-type]
        odoo_calendars=None,  # type: ignore[arg-type]  # unused in this path
        fallback=PunchDerivedRosterProvider.__new__(PunchDerivedRosterProvider),
        odoo_holidays=_FakeHolidays(holidays),  # type: ignore[arg-type]
    )


class TestHolidayExpansion:
    def test_company_holiday_fans_out_to_its_employees(self):
        # 1001, 1002 in company 7; 1003 in company 8. Holiday is company 7.
        provider = _provider(
            company_ids={"1001": 7, "1002": 7, "1003": 8},
            holidays={HOLIDAY: frozenset({7})},
        )
        result = provider.holiday_emp_codes_for_range(START, END)
        assert result == {HOLIDAY: frozenset({"1001", "1002"})}

    def test_multiple_companies_on_holiday(self):
        provider = _provider(
            company_ids={"1001": 7, "1002": 8, "1003": 9},
            holidays={HOLIDAY: frozenset({7, 8})},
        )
        result = provider.holiday_emp_codes_for_range(START, END)
        assert result == {HOLIDAY: frozenset({"1001", "1002"})}

    def test_company_with_no_roster_employees_yields_nothing(self):
        # Holiday is for company 99, which has no roster members → no rows.
        provider = _provider(
            company_ids={"1001": 7},
            holidays={HOLIDAY: frozenset({99})},
        )
        result = provider.holiday_emp_codes_for_range(START, END)
        assert result == {}

    def test_no_holidays_returns_empty_map(self):
        provider = _provider(company_ids={"1001": 7}, holidays={})
        assert provider.holiday_emp_codes_for_range(START, END) == {}

    def test_none_when_no_holiday_repo(self):
        provider = OdooRosterProvider(
            odoo_employees=_FakeEmployees({"1001": 7}),  # type: ignore[arg-type]
            odoo_calendars=None,  # type: ignore[arg-type]
            fallback=PunchDerivedRosterProvider.__new__(PunchDerivedRosterProvider),
            odoo_holidays=None,
        )
        assert provider.holiday_emp_codes_for_range(START, END) is None
