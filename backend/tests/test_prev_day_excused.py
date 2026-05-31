"""Excused employees (on leave / public holiday) who punched on their
excused day must NOT be flagged for missing-punch or incomplete-hours the
next day.

Real case (Saba, 2026-05): on leave for the day, came into the office to
grab an item, punched once. The next day she was flagged "Missing punch"
(and would have been flagged "Incomplete hours" had she punched twice).

The route layer fixes this by removing the excused emp_codes for the prior
working day from `working_emp_codes_prev_day` (via `exclude_excused`) before
running the prev-day detectors. These tests model that composition: subtract
the excused set, then assert the detector skips the person — and still fires
for a genuinely-incomplete non-excused colleague.
"""

from __future__ import annotations

from datetime import date, datetime

from app.features.dashboard.exceptions import (
    detect_prev_day_incomplete_hours,
    detect_prev_day_missing_punch,
)
from app.features.dashboard.models import ExceptionTag
from app.infra.roster import exclude_excused
from app.shared.models import Employee, Punch, ShiftRule

RULE = ShiftRule(start="09:00", grace_minutes=15)  # full day 480m
PREV_DAY = date(2026, 5, 24)  # the day Saba was on leave but punched

ROSTER = frozenset({"1001", "1002"})
NAMES = {"1001": "Saba", "1002": "Colleague"}
# Both scheduled in-office on prev_day before excused-filtering.
WORKING_PREV = frozenset({"1001", "1002"})


def _emp(code: str) -> Employee:
    return Employee(emp_code=code, name=NAMES[code], department="", active=True)


def _punch(code: str, hh: int, mm: int, tid: int) -> Punch:
    return Punch(
        transaction_id=tid,
        emp_code=code,
        employee_name=None,
        punch_time=datetime(PREV_DAY.year, PREV_DAY.month, PREV_DAY.day, hh, mm),
        punch_state="0",
    )


class TestMissingPunchSkipsExcused:
    def test_on_leave_single_punch_not_flagged(self):
        # Saba (1001) on leave prev_day, punched once. Colleague (1002)
        # genuinely punched once and IS on schedule.
        working_prev = exclude_excused(WORKING_PREV, frozenset({"1001"}))
        items = detect_prev_day_missing_punch(
            employees=[_emp("1001"), _emp("1002")],
            prev_punches=[_punch("1001", 13, 0, 1), _punch("1002", 8, 30, 2)],
            prev_day=PREV_DAY,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
            working_emp_codes_prev_day=working_prev,
        )
        codes = {i.emp_code for i in items}
        assert "1001" not in codes  # excused → skipped
        assert "1002" in codes  # genuinely missing a punch
        assert all(i.tag == ExceptionTag.MISSING_PUNCH for i in items)

    def test_on_holiday_single_punch_not_flagged(self):
        # Same shape, but excused via public holiday instead of leave.
        working_prev = exclude_excused(
            WORKING_PREV, None, frozenset({"1001"})
        )
        items = detect_prev_day_missing_punch(
            employees=[_emp("1001")],
            prev_punches=[_punch("1001", 13, 0, 1)],
            prev_day=PREV_DAY,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
            working_emp_codes_prev_day=working_prev,
        )
        assert items == []


class TestIncompleteHoursSkipsExcused:
    def test_on_leave_short_day_not_flagged(self):
        # Saba punched in AND out but only a few hours (she left after
        # grabbing the item). On leave → must not be flagged incomplete.
        working_prev = exclude_excused(WORKING_PREV, frozenset({"1001"}))
        items = detect_prev_day_incomplete_hours(
            employees=[_emp("1001"), _emp("1002")],
            prev_punches=[
                _punch("1001", 13, 0, 1),
                _punch("1001", 14, 30, 2),  # 1.5h
                _punch("1002", 9, 0, 3),
                _punch("1002", 13, 0, 4),  # 4h — genuinely short
            ],
            prev_day=PREV_DAY,
            rule=RULE,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
            working_emp_codes_prev_day=working_prev,
        )
        codes = {i.emp_code for i in items}
        assert "1001" not in codes  # excused → skipped
        assert "1002" in codes  # genuinely short on hours
        assert all(i.tag == ExceptionTag.INCOMPLETE_HOURS for i in items)
