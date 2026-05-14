"""Tests for the new exception detectors (absent, missing_punch) and their
composition in build_exceptions.

The detectors are pure functions so they're tested directly. Composition is
tested via build_exceptions to lock in tag ordering and filter behavior.
"""

from datetime import date, datetime

from app.features.dashboard.exceptions import (
    detect_absent,
    detect_prev_day_incomplete_hours,
    detect_prev_day_missing_punch,
)
from app.features.dashboard.models import ExceptionSeverity, ExceptionTag
from app.features.dashboard.service import build_exceptions

from tests._fixtures import DAY, RULE, emp, punch

# NOW values for "before cutoff" (10:30 absent cutoff per RULE) and "after".
BEFORE_CUTOFF = datetime(2026, 5, 12, 10, 0)
AFTER_CUTOFF = datetime(2026, 5, 12, 11, 0)
PREV_DAY = date(2026, 5, 11)


def prev_punch(emp_code: str, hh: int, mm: int, tid: int = 1):
    """Build a punch on PREV_DAY (the fixtures' punch() builder is fixed to DAY)."""
    from app.shared.models import Punch

    return Punch(
        transaction_id=tid,
        emp_code=emp_code,
        employee_name=None,
        punch_time=datetime(PREV_DAY.year, PREV_DAY.month, PREV_DAY.day, hh, mm),
        punch_state="0",
    )


class TestDetectAbsent:
    def test_flags_expected_employees_with_no_punch(self):
        employees = [emp("1001")]
        first_punches = {"1001": datetime(2026, 5, 12, 9, 5)}
        items = detect_absent(
            employees,
            first_punches,
            RULE,
            DAY,
            AFTER_CUTOFF,
            expected_emp_codes=frozenset({"1001", "1002", "1003"}),
            roster_names={"1001": "A", "1002": "B", "1003": "C"},
        )
        codes = {i.emp_code for i in items}
        assert codes == {"1002", "1003"}
        assert all(i.tag == ExceptionTag.ABSENT for i in items)
        assert all(i.severity == ExceptionSeverity.HIGH for i in items)
        # Names come from Odoo roster, not from the punch-derived employees list.
        names = {i.emp_code: i.name for i in items}
        assert names == {"1002": "B", "1003": "C"}

    def test_no_flags_before_cutoff(self):
        # Pre-10:30 we can't yet call anyone absent — they might arrive.
        items = detect_absent(
            [],
            {},
            RULE,
            DAY,
            BEFORE_CUTOFF,
            expected_emp_codes=frozenset({"1001"}),
        )
        assert items == []

    def test_no_roster_no_flags(self):
        # Without an Odoo roster, we can't list missing employees.
        items = detect_absent(
            [emp("1001")],
            {},
            RULE,
            DAY,
            AFTER_CUTOFF,
            expected_emp_codes=None,
        )
        assert items == []

    def test_uses_odoo_name_even_when_not_in_punch_derived_list(self):
        # The bug fix: employee absent today and not in the punch list —
        # name must come from Odoo, not fall back to the bare emp_code.
        items = detect_absent(
            employees=[],
            first_punches={},
            rule=RULE,
            day=DAY,
            now=AFTER_CUTOFF,
            expected_emp_codes=frozenset({"17"}),
            roster_names={"17": "Sara Khalil"},
        )
        assert len(items) == 1
        assert items[0].name == "Sara Khalil"

    def test_falls_back_to_code_when_no_odoo_configured(self):
        # Phase-1-style call: no roster_names → degrade to emp_code.
        items = detect_absent(
            employees=[],
            first_punches={},
            rule=RULE,
            day=DAY,
            now=AFTER_CUTOFF,
            expected_emp_codes=frozenset({"7777"}),
        )
        assert len(items) == 1
        assert items[0].name == "7777"


class TestDetectPrevDayMissingPunch:
    def test_single_punch_yesterday_flagged(self):
        prev_punches = [prev_punch("1001", 8, 30, 1)]  # only one event
        items = detect_prev_day_missing_punch(
            employees=[emp("1001")],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
        )
        assert len(items) == 1
        assert items[0].emp_code == "1001"
        assert items[0].tag == ExceptionTag.MISSING_PUNCH
        assert items[0].severity == ExceptionSeverity.MEDIUM
        assert PREV_DAY.strftime("%d-%m-%Y") in items[0].detail

    def test_missing_punch_uses_odoo_name(self):
        # Reproduces the screenshot bug: employee with single punch yesterday
        # and no punch today gets the Odoo name, not "17".
        prev_punches = [prev_punch("17", 8, 30, 1)]
        items = detect_prev_day_missing_punch(
            employees=[],  # not in today's punches
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            expected_emp_codes=frozenset({"17"}),
            roster_names={"17": "Omar Hasan"},
        )
        assert len(items) == 1
        assert items[0].name == "Omar Hasan"

    def test_missing_punch_hides_codes_not_in_odoo(self):
        # Odoo is configured (roster_names non-empty) but this code has no
        # match — row should be hidden, not shown with a placeholder.
        prev_punches = [prev_punch("9999", 8, 30, 1)]
        items = detect_prev_day_missing_punch(
            employees=[],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            roster_names={"1001": "Real Person"},
        )
        assert items == []

    def test_two_punches_not_flagged(self):
        prev_punches = [
            prev_punch("1001", 8, 30, 1),
            prev_punch("1001", 17, 0, 2),
        ]
        items = detect_prev_day_missing_punch(
            employees=[emp("1001")],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
        )
        assert items == []

    def test_no_prev_day_no_flags(self):
        items = detect_prev_day_missing_punch(
            employees=[emp("1001")],
            prev_punches=[],
            prev_day=None,
        )
        assert items == []

    def test_roster_filter_drops_non_employees(self):
        prev_punches = [
            prev_punch("1001", 8, 30, 1),
            prev_punch("9999", 9, 0, 2),  # visitor, single punch
        ]
        items = detect_prev_day_missing_punch(
            employees=[emp("1001")],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            expected_emp_codes=frozenset({"1001"}),
        )
        assert {i.emp_code for i in items} == {"1001"}


class TestDetectIncompleteHours:
    def test_flags_under_full_day(self):
        # 09:00 → 15:32 = 6h 32m worked, under the 8h threshold.
        prev_punches = [
            prev_punch("1001", 9, 0, 1),
            prev_punch("1001", 15, 32, 2),
        ]
        items = detect_prev_day_incomplete_hours(
            employees=[emp("1001", "Khaled")],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            rule=RULE,
        )
        assert len(items) == 1
        assert items[0].tag == ExceptionTag.INCOMPLETE_HOURS
        assert items[0].severity == ExceptionSeverity.MEDIUM
        # Detail follows the agreed format: "6h 32m / 8h 00m on DD-MM-YYYY".
        assert "6h 32m" in items[0].detail
        assert "8h 00m" in items[0].detail
        assert PREV_DAY.strftime("%d-%m-%Y") in items[0].detail

    def test_does_not_flag_when_full_day_met(self):
        # Exactly 8h — boundary should not flag.
        prev_punches = [
            prev_punch("1001", 9, 0, 1),
            prev_punch("1001", 17, 0, 2),
        ]
        items = detect_prev_day_incomplete_hours(
            employees=[emp("1001")],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            rule=RULE,
        )
        assert items == []

    def test_skips_single_punch_days(self):
        # That's missing-punch territory; mutual exclusion by construction.
        prev_punches = [prev_punch("1001", 9, 0, 1)]
        items = detect_prev_day_incomplete_hours(
            employees=[emp("1001")],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            rule=RULE,
        )
        assert items == []

    def test_uses_odoo_name(self):
        prev_punches = [
            prev_punch("80", 8, 45, 1),
            prev_punch("80", 14, 0, 2),
        ]
        items = detect_prev_day_incomplete_hours(
            employees=[],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            rule=RULE,
            expected_emp_codes=frozenset({"80"}),
            roster_names={"80": "Omar Basem Elhasan"},
        )
        assert len(items) == 1
        assert items[0].name == "Omar Basem Elhasan"

    def test_roster_filter_drops_non_employees(self):
        prev_punches = [
            prev_punch("1001", 9, 0, 1),
            prev_punch("1001", 14, 0, 2),
            prev_punch("9999", 9, 0, 3),  # visitor, also short day
            prev_punch("9999", 14, 0, 4),
        ]
        items = detect_prev_day_incomplete_hours(
            employees=[],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            rule=RULE,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "Khaled"},
        )
        assert {i.emp_code for i in items} == {"1001"}


class TestBuildExceptionsComposition:
    def test_absent_rows_appear_before_late_rows(self):
        # 1001 late, 1002 absent → absent comes first per _TAG_ORDER.
        employees = [emp("1001"), emp("1002")]
        punches = [punch("1001", 9, 30, 1)]
        result = build_exceptions(
            employees,
            punches,
            RULE,
            DAY,
            AFTER_CUTOFF,
            expected_emp_codes=frozenset({"1001", "1002"}),
        )
        tags = [i.tag for i in result.items]
        assert tags[0] == ExceptionTag.ABSENT
        assert ExceptionTag.LATE in tags
        assert tags.index(ExceptionTag.ABSENT) < tags.index(ExceptionTag.LATE)

    def test_missing_punch_appears_between_absent_and_late(self):
        # 1001 absent today, 1002 on time today but missing punch yesterday,
        # 1003 late today. Tag order must be absent → missing → late.
        employees = [emp("1001"), emp("1002"), emp("1003")]
        punches = [
            punch("1002", 9, 0, 1),   # on time today
            punch("1003", 9, 30, 2),  # late today
        ]
        prev_punches = [prev_punch("1002", 8, 0, 1)]
        result = build_exceptions(
            employees,
            punches,
            RULE,
            DAY,
            AFTER_CUTOFF,
            expected_emp_codes=frozenset({"1001", "1002", "1003"}),
            prev_working_day=PREV_DAY,
            prev_working_day_punches=prev_punches,
        )
        tags = [i.tag for i in result.items]
        assert tags == [
            ExceptionTag.ABSENT,
            ExceptionTag.MISSING_PUNCH,
            ExceptionTag.LATE,
        ]

    def test_full_tag_ordering_includes_incomplete_hours(self):
        # 1001 absent today; 1002 on time today but single-punch yesterday
        # (missing_punch); 1003 worked 6h yesterday (incomplete_hours) and
        # on time today; 1004 late today.
        employees = [emp("1001"), emp("1002"), emp("1003"), emp("1004")]
        punches = [
            punch("1002", 9, 0, 1),    # on time today
            punch("1003", 9, 0, 2),    # on time today
            punch("1004", 9, 30, 3),   # late today
        ]
        prev_punches = [
            prev_punch("1002", 8, 0, 1),    # single punch
            prev_punch("1003", 9, 0, 2),    # 6h day → incomplete
            prev_punch("1003", 15, 0, 3),
        ]
        result = build_exceptions(
            employees,
            punches,
            RULE,
            DAY,
            AFTER_CUTOFF,
            expected_emp_codes=frozenset({"1001", "1002", "1003", "1004"}),
            prev_working_day=PREV_DAY,
            prev_working_day_punches=prev_punches,
        )
        tags = [i.tag for i in result.items]
        assert tags == [
            ExceptionTag.ABSENT,
            ExceptionTag.MISSING_PUNCH,
            ExceptionTag.INCOMPLETE_HOURS,
            ExceptionTag.LATE,
        ]

    def test_filter_incomplete_hours_returns_only_those(self):
        employees = [emp("1001"), emp("1002")]
        punches = [punch("1001", 9, 0, 1), punch("1002", 9, 0, 2)]
        prev_punches = [
            prev_punch("1001", 9, 0, 1),
            prev_punch("1001", 15, 0, 2),  # 6h → incomplete
            prev_punch("1002", 9, 0, 3),
            prev_punch("1002", 17, 0, 4),  # 8h → fine
        ]
        result = build_exceptions(
            employees,
            punches,
            RULE,
            DAY,
            AFTER_CUTOFF,
            filter_type="incomplete_hours",
            expected_emp_codes=frozenset({"1001", "1002"}),
            prev_working_day=PREV_DAY,
            prev_working_day_punches=prev_punches,
        )
        assert result.total == 1
        assert result.items[0].emp_code == "1001"

    def test_employee_can_appear_in_multiple_categories(self):
        # 1001 was absent yesterday-style: single punch yesterday AND absent
        # today. Both flags should fire — they're orthogonal problems.
        employees = [emp("1001")]
        prev_punches = [prev_punch("1001", 8, 0, 1)]
        result = build_exceptions(
            employees,
            [],
            RULE,
            DAY,
            AFTER_CUTOFF,
            expected_emp_codes=frozenset({"1001"}),
            prev_working_day=PREV_DAY,
            prev_working_day_punches=prev_punches,
        )
        tags = {i.tag for i in result.items}
        assert tags == {ExceptionTag.ABSENT, ExceptionTag.MISSING_PUNCH}

    def test_filter_missing_punch_returns_only_those(self):
        employees = [emp("1001"), emp("1002")]
        punches = [punch("1002", 9, 30, 1)]
        prev_punches = [prev_punch("1001", 8, 0, 1)]
        result = build_exceptions(
            employees,
            punches,
            RULE,
            DAY,
            AFTER_CUTOFF,
            filter_type="missing_punch",
            expected_emp_codes=frozenset({"1001", "1002"}),
            prev_working_day=PREV_DAY,
            prev_working_day_punches=prev_punches,
        )
        assert result.total == 1
        assert result.items[0].emp_code == "1001"
        assert result.items[0].tag == ExceptionTag.MISSING_PUNCH

    def test_filter_absent_returns_only_absent(self):
        employees = [emp("1001"), emp("1002")]
        punches = [punch("1001", 9, 30, 1)]  # 1001 late, 1002 absent
        result = build_exceptions(
            employees,
            punches,
            RULE,
            DAY,
            AFTER_CUTOFF,
            filter_type="absent",
            expected_emp_codes=frozenset({"1001", "1002"}),
        )
        assert result.total == 1
        assert result.items[0].emp_code == "1002"
        assert result.items[0].tag == ExceptionTag.ABSENT
