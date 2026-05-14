"""WFH (work-from-home) day behavior — Thursday is a no-violation day.

A Thursday is a real working day, but attendance violations don't fire:
no Absent tile count, no Late flagging, no Missing-punch / Incomplete-hours
exceptions for the day before either when that day is also WFH.
Real punches still count toward Present so the office headcount is honest.

Phase 3 will replace this with per-employee WFH data from Odoo.
"""

from __future__ import annotations

from datetime import date, datetime

from app.features.dashboard.exceptions import (
    detect_absent,
    detect_late,
    detect_prev_day_incomplete_hours,
    detect_prev_day_missing_punch,
)
from app.features.dashboard.service import build_overview
from app.shared.models import Punch, ShiftRule

# 2026-05-14 = Thursday (weekday 3), the day we want to treat as WFH.
THURSDAY = date(2026, 5, 14)
WEDNESDAY = date(2026, 5, 13)  # for missing/incomplete prev-day cases
NOW_THURS = datetime(2026, 5, 14, 11, 0)
NOW_WED = datetime(2026, 5, 13, 11, 0)
WFH_RULE = ShiftRule(
    start="09:00", grace_minutes=15, absent_after="10:30", wfh_weekdays=[3]
)


def _emp(code: str, name: str = "Test"):
    from app.shared.models import Employee

    return Employee(emp_code=code, name=name, department="", active=True)


def _punch(emp_code: str, day: date, hh: int, mm: int, tid: int = 1) -> Punch:
    return Punch(
        transaction_id=tid,
        emp_code=emp_code,
        employee_name=None,
        punch_time=datetime(day.year, day.month, day.day, hh, mm),
        punch_state="0",
    )


class TestOverviewOnWFHDay:
    def test_absent_is_zero_on_wfh_day(self):
        result = build_overview(
            employees=[_emp("1001"), _emp("1002")],
            punches=[],
            rule=WFH_RULE,
            day=THURSDAY,
            now=NOW_THURS,
            expected_emp_codes=frozenset({"1001", "1002"}),
        )
        assert result.absent == 0
        assert result.present == 0

    def test_late_is_zero_on_wfh_day_even_if_late_punches_exist(self):
        # Someone punching in at 09:30 on Thursday is not "late" — they
        # chose to come in on a WFH day.
        result = build_overview(
            employees=[_emp("1001")],
            punches=[_punch("1001", THURSDAY, 9, 30)],
            rule=WFH_RULE,
            day=THURSDAY,
            now=NOW_THURS,
            expected_emp_codes=frozenset({"1001"}),
        )
        assert result.late == 0
        # Present still counts: they showed up to the office.
        assert result.present == 1

    def test_non_wfh_day_unchanged(self):
        # Wednesday is a regular workday — absent still fires.
        result = build_overview(
            employees=[_emp("1001")],
            punches=[],
            rule=WFH_RULE,
            day=WEDNESDAY,
            now=NOW_WED,
            expected_emp_codes=frozenset({"1001"}),
        )
        assert result.absent == 1


class TestDetectorsOnWFHDay:
    def test_detect_absent_skipped_on_wfh(self):
        items = detect_absent(
            employees=[_emp("1001")],
            first_punches={},
            rule=WFH_RULE,
            day=THURSDAY,
            now=NOW_THURS,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "Khaled"},
        )
        assert items == []

    def test_detect_late_skipped_on_wfh(self):
        items = detect_late(
            employees=[_emp("1001")],
            first_punches={"1001": datetime(2026, 5, 14, 9, 45)},
            rule=WFH_RULE,
            day=THURSDAY,
            now=NOW_THURS,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "Khaled"},
        )
        assert items == []

    def test_missing_punch_skipped_when_prev_day_is_wfh(self):
        # Imagine "today" is Friday/Sunday — the lookback found Thursday
        # with a single punch. WFH means we don't flag.
        prev_punches = [_punch("1001", THURSDAY, 9, 0)]
        items = detect_prev_day_missing_punch(
            employees=[_emp("1001")],
            prev_punches=prev_punches,
            prev_day=THURSDAY,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "Khaled"},
            wfh_weekdays=[3],
        )
        assert items == []

    def test_incomplete_hours_skipped_when_prev_day_is_wfh(self):
        # 6h day on Thursday — should not be flagged since Thursday is WFH.
        prev_punches = [
            _punch("1001", THURSDAY, 9, 0, 1),
            _punch("1001", THURSDAY, 15, 0, 2),
        ]
        items = detect_prev_day_incomplete_hours(
            employees=[_emp("1001")],
            prev_punches=prev_punches,
            prev_day=THURSDAY,
            rule=WFH_RULE,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "Khaled"},
        )
        assert items == []

    def test_missing_punch_still_fires_on_non_wfh_prev_day(self):
        # Same scenario but prev_day is Wednesday — should fire.
        prev_punches = [_punch("1001", WEDNESDAY, 9, 0)]
        items = detect_prev_day_missing_punch(
            employees=[_emp("1001")],
            prev_punches=prev_punches,
            prev_day=WEDNESDAY,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "Khaled"},
            wfh_weekdays=[3],
        )
        assert len(items) == 1
