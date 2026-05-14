"""Tests for the Odoo employee repository and the absent count it feeds.

The Odoo XML-RPC client is faked end-to-end via a stub OdooClient subclass —
no network calls, no live Odoo. We're only exercising:
  1. Normalization of x_studio_employee_code values (False, 0, "0", "", ints).
  2. TTL cache behavior (single fetch per window, single-flight refill).
  3. Service-level absent math when expected_emp_codes is provided.
"""

from __future__ import annotations

from typing import Any

from app.features.dashboard.service import build_overview
from app.infra.odoo_client import OdooClient
from app.infra.odoo_employees import (
    EMP_CODE_FIELD,
    NAME_FIELD,
    OdooEmployeeRepository,
)

from tests._fixtures import DAY, NOW, RULE, emp, punch


class FakeOdooClient(OdooClient):
    """Bypasses XML-RPC entirely; canned rows for `hr.employee` search_read."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        # Skip parent __init__ — no URL/auth needed for the fake.
        self._rows = rows
        self.call_count = 0

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        batch_size: int = 500,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        self.call_count += 1
        return [{k: row.get(k) for k in fields} for row in self._rows]


class TestOdooEmployeeRepository:
    def test_normalizes_emp_codes_and_drops_zero_and_blank(self):
        rows = [
            {EMP_CODE_FIELD: "1001"},
            {EMP_CODE_FIELD: 1002},        # int from Odoo
            {EMP_CODE_FIELD: "  1003  "},  # whitespace
            {EMP_CODE_FIELD: "0"},         # explicit zero string
            {EMP_CODE_FIELD: 0},           # explicit zero int
            {EMP_CODE_FIELD: False},       # Odoo "unset"
            {EMP_CODE_FIELD: ""},          # empty string
            {EMP_CODE_FIELD: None},        # null
        ]
        repo = OdooEmployeeRepository(FakeOdooClient(rows), cache_ttl_seconds=60)
        result = repo.expected_emp_codes()
        assert result == frozenset({"1001", "1002", "1003"})

    def test_cache_hits_avoid_refetch_within_ttl(self):
        client = FakeOdooClient([{EMP_CODE_FIELD: "1001"}])
        repo = OdooEmployeeRepository(client, cache_ttl_seconds=300)
        repo.expected_emp_codes()
        repo.expected_emp_codes()
        repo.expected_emp_codes()
        assert client.call_count == 1

    def test_invalidate_forces_refetch(self):
        client = FakeOdooClient([{EMP_CODE_FIELD: "1001"}])
        repo = OdooEmployeeRepository(client, cache_ttl_seconds=300)
        repo.expected_emp_codes()
        repo.invalidate()
        repo.expected_emp_codes()
        assert client.call_count == 2

    def test_display_names_returns_code_to_name_mapping(self):
        rows = [
            {EMP_CODE_FIELD: "1001", NAME_FIELD: "Omar Hasan"},
            {EMP_CODE_FIELD: 17, NAME_FIELD: "Sara Khalil"},
            {EMP_CODE_FIELD: "38", NAME_FIELD: False},  # Odoo "unset" name
        ]
        repo = OdooEmployeeRepository(FakeOdooClient(rows), cache_ttl_seconds=60)
        names = repo.display_names()
        assert names["1001"] == "Omar Hasan"
        assert names["17"] == "Sara Khalil"
        # Unset name falls back to the emp_code so the row stays usable.
        assert names["38"] == "38"

    def test_display_names_and_codes_share_one_fetch(self):
        client = FakeOdooClient([{EMP_CODE_FIELD: "1001", NAME_FIELD: "A"}])
        repo = OdooEmployeeRepository(client, cache_ttl_seconds=300)
        repo.expected_emp_codes()
        repo.display_names()
        repo.expected_emp_codes()
        assert client.call_count == 1


class TestOverviewAbsent:
    def test_absent_is_expected_minus_punched(self):
        # Expected roster: 1001, 1002, 1003. Only 1001 and 1002 punched.
        employees = [emp("1001"), emp("1002")]
        punches = [punch("1001", 9, 5, 1), punch("1002", 9, 32, 2)]
        result = build_overview(
            employees,
            punches,
            RULE,
            DAY,
            NOW,
            expected_emp_codes=frozenset({"1001", "1002", "1003"}),
        )
        assert result.present == 2
        assert result.late == 1
        assert result.absent == 1
        # Present + Absent must equal roster size — the headline invariant.
        assert result.present + result.absent == 3

    def test_absent_zero_when_everyone_punched(self):
        employees = [emp("1001"), emp("1002")]
        punches = [punch("1001", 9, 5, 1), punch("1002", 9, 32, 2)]
        result = build_overview(
            employees,
            punches,
            RULE,
            DAY,
            NOW,
            expected_emp_codes=frozenset({"1001", "1002"}),
        )
        assert result.absent == 0
        assert result.present + result.absent == 2

    def test_non_roster_punchers_excluded_from_present(self):
        # 9999 punched but isn't on the expected roster — they must NOT
        # inflate Present, otherwise Present + Absent > roster size.
        # This is the regression from the 92/94/etc bug.
        employees = [emp("1001"), emp("9999")]  # 9999 derived from punches
        punches = [punch("1001", 9, 5, 1), punch("9999", 9, 10, 2)]
        result = build_overview(
            employees,
            punches,
            RULE,
            DAY,
            NOW,
            expected_emp_codes=frozenset({"1001", "1002"}),
        )
        # 1001 punched (in roster), 9999 punched (NOT in roster, ignored),
        # 1002 didn't punch (in roster → absent).
        assert result.present == 1
        assert result.absent == 1
        assert result.present + result.absent == 2

    def test_absent_none_when_no_roster(self):
        # Phase-1 fallback path: no expected set → tile renders "—".
        result = build_overview([emp("1001")], [punch("1001", 9, 5, 1)], RULE, DAY, NOW)
        assert result.absent is None


class TestExceptionsRosterFilter:
    def test_non_roster_late_punchers_excluded(self):
        # 9999 is late but not in the Odoo roster — must not appear.
        from app.features.dashboard.service import build_exceptions

        employees = [emp("1001"), emp("9999")]
        punches = [punch("1001", 9, 5, 1), punch("9999", 9, 45, 2)]
        result = build_exceptions(
            employees,
            punches,
            RULE,
            DAY,
            NOW,
            expected_emp_codes=frozenset({"1001"}),
        )
        assert all(i.emp_code != "9999" for i in result.items)
