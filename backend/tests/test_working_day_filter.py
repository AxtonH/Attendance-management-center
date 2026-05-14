"""Tests for the working-day filter across Present/Absent and the detectors.

DAY = 2026-05-12 = Tuesday (Python weekday 1).
PREV_DAY = 2026-05-11 = Monday (weekday 0).
We use Friday and Saturday cases by overriding `working_emp_codes*` directly
in the tests — the parser/repo composition is covered in their own files.
"""

from __future__ import annotations

from app.features.dashboard.exceptions import (
    detect_absent,
    detect_prev_day_incomplete_hours,
    detect_prev_day_missing_punch,
)
from app.features.dashboard.models import ExceptionTag
from app.features.dashboard.service import build_overview

from tests._fixtures import DAY, NOW, RULE, emp, punch
from tests.test_exception_detectors import AFTER_CUTOFF, PREV_DAY, prev_punch


class TestOverviewWorkingDayFilter:
    def test_absent_excludes_off_schedule_employees(self):
        # Roster: 1001 (working today), 1002 (NOT working today).
        # Only 1001 should count toward Absent if neither punched.
        result = build_overview(
            employees=[emp("1001"), emp("1002")],
            punches=[],
            rule=RULE,
            day=DAY,
            now=NOW,
            expected_emp_codes=frozenset({"1001", "1002"}),
            working_emp_codes=frozenset({"1001"}),
        )
        assert result.absent == 1
        assert result.present == 0
        # Invariant: Present + Absent = working roster size.
        assert result.present + result.absent == 1

    def test_invariant_present_plus_absent_equals_working_roster(self):
        # 3-employee roster, only 2 working today, 1 punched.
        result = build_overview(
            employees=[emp("1001"), emp("1002"), emp("1003")],
            punches=[punch("1001", 9, 0, 1)],
            rule=RULE,
            day=DAY,
            now=NOW,
            expected_emp_codes=frozenset({"1001", "1002", "1003"}),
            working_emp_codes=frozenset({"1001", "1002"}),
        )
        assert result.present == 1
        assert result.absent == 1
        assert result.present + result.absent == 2

    def test_no_working_set_falls_back_to_full_roster(self):
        # working_emp_codes=None means "no schedule info" — behaves like before.
        result = build_overview(
            employees=[emp("1001"), emp("1002")],
            punches=[],
            rule=RULE,
            day=DAY,
            now=NOW,
            expected_emp_codes=frozenset({"1001", "1002"}),
            working_emp_codes=None,
        )
        assert result.absent == 2


class TestDetectAbsentWorkingDayFilter:
    def test_off_schedule_employee_not_flagged_absent(self):
        # Bug scenario: 1002 has a Mon–Fri schedule, today is Sunday →
        # they're not on-shift, so absent shouldn't fire.
        items = detect_absent(
            employees=[emp("1002")],
            first_punches={},
            rule=RULE,
            day=DAY,
            now=AFTER_CUTOFF,
            expected_emp_codes=frozenset({"1001", "1002"}),
            roster_names={"1001": "A", "1002": "B"},
            working_emp_codes=frozenset({"1001"}),
        )
        codes = {i.emp_code for i in items}
        assert codes == {"1001"}
        assert "1002" not in codes

    def test_missing_working_set_keeps_old_behavior(self):
        # working_emp_codes=None → no filter applied → both flagged absent.
        items = detect_absent(
            employees=[],
            first_punches={},
            rule=RULE,
            day=DAY,
            now=AFTER_CUTOFF,
            expected_emp_codes=frozenset({"1001", "1002"}),
            roster_names={"1001": "A", "1002": "B"},
        )
        assert {i.emp_code for i in items} == {"1001", "1002"}


class TestPrevDayDetectorsWorkingDayFilter:
    def test_missing_punch_skips_off_schedule_prev_day(self):
        # 1001 had a single punch on PREV_DAY, but PREV_DAY isn't their
        # working day → not flagged.
        prev_punches = [prev_punch("1001", 8, 30, 1)]
        items = detect_prev_day_missing_punch(
            employees=[emp("1001")],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "A"},
            working_emp_codes_prev_day=frozenset(),  # 1001 NOT working prev day
        )
        assert items == []

    def test_missing_punch_fires_when_on_schedule(self):
        prev_punches = [prev_punch("1001", 8, 30, 1)]
        items = detect_prev_day_missing_punch(
            employees=[emp("1001")],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "A"},
            working_emp_codes_prev_day=frozenset({"1001"}),
        )
        assert len(items) == 1
        assert items[0].tag == ExceptionTag.MISSING_PUNCH

    def test_incomplete_hours_skips_off_schedule_prev_day(self):
        # 6-hour day on PREV_DAY, but PREV_DAY isn't their workday.
        prev_punches = [
            prev_punch("1001", 9, 0, 1),
            prev_punch("1001", 15, 0, 2),
        ]
        items = detect_prev_day_incomplete_hours(
            employees=[emp("1001")],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            rule=RULE,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "A"},
            working_emp_codes_prev_day=frozenset(),
        )
        assert items == []

    def test_incomplete_hours_fires_when_on_schedule(self):
        prev_punches = [
            prev_punch("1001", 9, 0, 1),
            prev_punch("1001", 15, 0, 2),
        ]
        items = detect_prev_day_incomplete_hours(
            employees=[emp("1001")],
            prev_punches=prev_punches,
            prev_day=PREV_DAY,
            rule=RULE,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "A"},
            working_emp_codes_prev_day=frozenset({"1001"}),
        )
        assert len(items) == 1
        assert items[0].tag == ExceptionTag.INCOMPLETE_HOURS
