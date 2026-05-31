"""Absent-row behavior for the Employees daily + weekly/monthly builders.

Covers the addition of absent employees to the Employees views:
  - Daily: roster employees expected today who never punched appear as
    rows with null punches and `absent=True`.
  - Weekly/monthly/range: absent days become `absent=True` child rows,
    and employees who never punched but were scheduled at least once in
    the range still get a parent row (all-absent children).

Window: Sun 2026-05-10 .. Tue 2026-05-12. `LATE_NOW` is past every day's
absent cutoff so all three days are "settled".
"""

from __future__ import annotations

from datetime import date, datetime

from app.features.employees.service import (
    build_employees_today,
    build_employees_week,
)
from app.shared.models import Employee, Punch, ShiftRule

RULE = ShiftRule(start="09:00", grace_minutes=15)  # cutoff 09:15, no WFH days

SUN = date(2026, 5, 10)
MON = date(2026, 5, 11)
TUE = date(2026, 5, 12)
DAYS = [SUN, MON, TUE]

# Well past the latest day's cutoff → every day is settled.
LATE_NOW = datetime(2026, 5, 12, 18, 0)

ROSTER = frozenset({"1001", "1002", "1003"})
NAMES = {"1001": "Alice", "1002": "Bob", "1003": "Cara"}
# Everyone is scheduled in-office every day in the window.
WORKING = {d: ROSTER for d in DAYS}


def _emp(code: str) -> Employee:
    return Employee(emp_code=code, name=NAMES[code], department="", active=True)


def _punch(code: str, day: date, hh: int, mm: int, tid: int) -> Punch:
    return Punch(
        transaction_id=tid,
        emp_code=code,
        employee_name=None,
        punch_time=datetime(day.year, day.month, day.day, hh, mm),
        punch_state="0",
    )


class TestDailyAbsent:
    def test_absent_employee_gets_row_with_null_punches(self):
        # 1001 punched, 1002 + 1003 didn't.
        result = build_employees_today(
            employees=[_emp("1001")],
            punches=[_punch("1001", TUE, 9, 0, 1)],
            day=TUE,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
            rule=RULE,
            now=LATE_NOW,
            working_emp_codes=ROSTER,
        )
        by_code = {r.emp_code: r for r in result.rows}
        assert by_code["1001"].absent is False
        assert by_code["1001"].punch_in is not None
        for code in ("1002", "1003"):
            assert by_code[code].absent is True
            assert by_code[code].punch_in is None
            assert by_code[code].punch_out is None
            assert by_code[code].worked_minutes is None

    def test_no_absent_without_rule_or_now(self):
        # Phase-1 style call: no rule/now → no absent rows (old behavior).
        result = build_employees_today(
            employees=[_emp("1001")],
            punches=[_punch("1001", TUE, 9, 0, 1)],
            day=TUE,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
        )
        assert {r.emp_code for r in result.rows} == {"1001"}

    def test_off_schedule_employee_not_absent(self):
        # 1003 not scheduled today → not flagged absent even with no punch.
        result = build_employees_today(
            employees=[],
            punches=[],
            day=TUE,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
            rule=RULE,
            now=LATE_NOW,
            working_emp_codes=frozenset({"1001", "1002"}),
        )
        codes = {r.emp_code for r in result.rows}
        assert codes == {"1001", "1002"}  # both absent, 1003 excluded


class TestWeeklyAbsent:
    def test_fully_absent_employee_gets_parent_row(self):
        # Only 1001 ever punches (all 3 days). 1002/1003 never punch but
        # are scheduled all week → they appear with all-absent children.
        punches_by_day = {
            SUN: [_punch("1001", SUN, 9, 0, 1)],
            MON: [_punch("1001", MON, 9, 0, 2)],
            TUE: [_punch("1001", TUE, 9, 0, 3)],
        }
        result = build_employees_week(
            employees=[_emp("1001")],
            punches_by_day=punches_by_day,
            days=DAYS,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
            rule=RULE,
            now=LATE_NOW,
            working_emp_codes_by_day=WORKING,
        )
        by_code = {r.emp_code: r for r in result.rows}
        assert set(by_code) == {"1001", "1002", "1003"}

        bob = by_code["1002"]
        assert bob.days_worked == 0
        assert bob.total_worked_minutes == 0
        assert len(bob.days) == 3
        assert all(d.absent for d in bob.days)
        assert all(d.punch_in is None for d in bob.days)
        # Chronological order preserved.
        assert [d.date for d in bob.days] == [
            SUN.isoformat(),
            MON.isoformat(),
            TUE.isoformat(),
        ]

    def test_partial_week_interleaves_worked_and_absent(self):
        # 1001 works Sun + Tue, absent Mon. days_worked counts worked only.
        punches_by_day = {
            SUN: [
                _punch("1001", SUN, 9, 0, 1),
                _punch("1001", SUN, 17, 0, 2),
            ],
            MON: [],
            TUE: [
                _punch("1001", TUE, 9, 0, 3),
                _punch("1001", TUE, 17, 0, 4),
            ],
        }
        result = build_employees_week(
            employees=[_emp("1001")],
            punches_by_day=punches_by_day,
            days=DAYS,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "Alice"},
            rule=RULE,
            now=LATE_NOW,
            working_emp_codes_by_day={d: frozenset({"1001"}) for d in DAYS},
        )
        row = result.rows[0]
        assert row.emp_code == "1001"
        assert row.days_worked == 2
        # 8h each worked day, absent day contributes nothing.
        assert row.total_worked_minutes == 2 * 480
        assert [(d.date, d.absent) for d in row.days] == [
            (SUN.isoformat(), False),
            (MON.isoformat(), True),
            (TUE.isoformat(), False),
        ]

    def test_no_absent_without_rule_or_now(self):
        # Without rule/now the builder keeps old behavior: only punched
        # days, no fully-absent employees.
        punches_by_day = {
            SUN: [_punch("1001", SUN, 9, 0, 1)],
            MON: [],
            TUE: [],
        }
        result = build_employees_week(
            employees=[_emp("1001")],
            punches_by_day=punches_by_day,
            days=DAYS,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
        )
        assert {r.emp_code for r in result.rows} == {"1001"}
        row = result.rows[0]
        assert row.days_worked == 1
        assert len(row.days) == 1

    def test_current_day_before_cutoff_not_absent(self):
        # `now` is 09:05 on TUE — before TUE's 09:15 cutoff. TUE isn't
        # settled, so no absent rows for TUE; SUN/MON (past) still settle.
        early_now = datetime(2026, 5, 12, 9, 5)
        result = build_employees_week(
            employees=[],
            punches_by_day={SUN: [], MON: [], TUE: []},
            days=DAYS,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "Alice"},
            rule=RULE,
            now=early_now,
            working_emp_codes_by_day={d: frozenset({"1001"}) for d in DAYS},
        )
        row = result.rows[0]
        dates = {d.date for d in row.days}
        assert SUN.isoformat() in dates
        assert MON.isoformat() in dates
        assert TUE.isoformat() not in dates  # not yet settled


class TestDailyOnLeave:
    def test_on_leave_replaces_absent_for_full_day_leave(self):
        # 1002 didn't punch but has approved full-day leave → on_leave,
        # not absent. 1003 also absent but no leave → stays absent.
        result = build_employees_today(
            employees=[],
            punches=[],
            day=TUE,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
            rule=RULE,
            now=LATE_NOW,
            working_emp_codes=ROSTER,
            on_leave_emp_codes=frozenset({"1002"}),
        )
        by_code = {r.emp_code: r for r in result.rows}
        assert by_code["1002"].on_leave is True
        assert by_code["1002"].absent is False
        assert by_code["1002"].punch_in is None
        assert by_code["1003"].absent is True
        assert by_code["1003"].on_leave is False

    def test_leave_does_not_affect_present_employees(self):
        # A punched employee who somehow also has a leave code stays a
        # normal present row (leave only reclassifies would-be absences).
        result = build_employees_today(
            employees=[_emp("1001")],
            punches=[_punch("1001", TUE, 9, 0, 1)],
            day=TUE,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
            rule=RULE,
            now=LATE_NOW,
            working_emp_codes=ROSTER,
            on_leave_emp_codes=frozenset({"1001"}),
        )
        alice = next(r for r in result.rows if r.emp_code == "1001")
        assert alice.on_leave is False
        assert alice.absent is False
        assert alice.punch_in is not None


class TestWeeklyOnLeave:
    def test_leave_day_is_on_leave_not_absent_and_not_worked(self):
        # 1001 works SUN, on leave MON, absent TUE.
        punches_by_day = {
            SUN: [
                _punch("1001", SUN, 9, 0, 1),
                _punch("1001", SUN, 17, 0, 2),
            ],
            MON: [],
            TUE: [],
        }
        result = build_employees_week(
            employees=[_emp("1001")],
            punches_by_day=punches_by_day,
            days=DAYS,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "Alice"},
            rule=RULE,
            now=LATE_NOW,
            working_emp_codes_by_day={d: frozenset({"1001"}) for d in DAYS},
            on_leave_emp_codes_by_day={MON: frozenset({"1001"})},
        )
        row = result.rows[0]
        by_date = {d.date: d for d in row.days}
        assert by_date[MON.isoformat()].on_leave is True
        assert by_date[MON.isoformat()].absent is False
        assert by_date[TUE.isoformat()].absent is True
        # Only SUN counts as worked; leave + absent days don't.
        assert row.days_worked == 1
        assert row.total_worked_minutes == 480

    def test_fully_on_leave_employee_gets_parent_row(self):
        # 1002 never punches but is on leave all three days → parent row
        # with all-on-leave children, zero worked days.
        punches_by_day = {
            SUN: [_punch("1001", SUN, 9, 0, 1)],
            MON: [_punch("1001", MON, 9, 0, 2)],
            TUE: [_punch("1001", TUE, 9, 0, 3)],
        }
        result = build_employees_week(
            employees=[_emp("1001")],
            punches_by_day=punches_by_day,
            days=DAYS,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
            rule=RULE,
            now=LATE_NOW,
            working_emp_codes_by_day=WORKING,
            on_leave_emp_codes_by_day={d: frozenset({"1002"}) for d in DAYS},
        )
        by_code = {r.emp_code: r for r in result.rows}
        bob = by_code["1002"]
        assert bob.days_worked == 0
        assert len(bob.days) == 3
        assert all(d.on_leave and not d.absent for d in bob.days)
        # 1003 has no leave → all-absent children.
        cara = by_code["1003"]
        assert all(d.absent and not d.on_leave for d in cara.days)
