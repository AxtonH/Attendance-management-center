"""Tests for build_departments_rollup.

Reuses the existing fixtures: DAY is Tue 2026-05-12 (a non-WFH workday)
so the math behaves normally. WFH-day suppression has its own targeted
test against THURSDAY.
"""

from __future__ import annotations

from datetime import date, datetime

from app.features.dashboard.service import build_departments_rollup
from app.shared.models import ShiftRule

from tests._fixtures import DAY, NOW, RULE, punch


WFH_RULE = ShiftRule(
    start="09:00", grace_minutes=15, absent_after="10:30", wfh_weekdays=[3]
)
THURSDAY = date(2026, 5, 14)
NOW_THURS = datetime(2026, 5, 14, 11, 0)


class TestBuildDepartmentsRollup:
    def test_groups_by_department(self):
        dept_map = {
            "1001": "Design",
            "1002": "Design",
            "1003": "Strategy",
        }
        # 1001 on time, 1002 late, 1003 didn't punch.
        punches = [punch("1001", 9, 0, 1), punch("1002", 9, 30, 2)]
        result = build_departments_rollup(
            punches,
            RULE,
            DAY,
            NOW,
            dept_map,
            expected_emp_codes=frozenset({"1001", "1002", "1003"}),
        )
        by_name = {r.name: r for r in result.departments}
        assert by_name["Design"].expected == 2
        assert by_name["Design"].present == 2
        assert by_name["Design"].late == 1
        assert by_name["Design"].absent == 0
        assert by_name["Strategy"].expected == 1
        assert by_name["Strategy"].present == 0
        assert by_name["Strategy"].late == 0
        assert by_name["Strategy"].absent == 1

    def test_invariant_present_plus_absent_equals_expected(self):
        # Per-department invariant matches the tile-level one.
        dept_map = {f"100{i}": "Tech" for i in range(1, 5)}
        punches = [punch("1001", 9, 0, 1), punch("1003", 9, 30, 2)]
        result = build_departments_rollup(
            punches,
            RULE,
            DAY,
            NOW,
            dept_map,
            expected_emp_codes=frozenset(dept_map.keys()),
        )
        tech = next(r for r in result.departments if r.name == "Tech")
        assert tech.expected == 4
        assert tech.present + tech.absent == tech.expected

    def test_empty_departments_are_dropped(self):
        # Only "Design" has anyone working today — "Strategy" should not appear.
        dept_map = {
            "1001": "Design",
            "1002": "Strategy",  # not working today
        }
        result = build_departments_rollup(
            punches=[punch("1001", 9, 0, 1)],
            rule=RULE,
            day=DAY,
            now=NOW,
            department_by_emp_code=dept_map,
            expected_emp_codes=frozenset({"1001", "1002"}),
            working_emp_codes=frozenset({"1001"}),
        )
        names = {r.name for r in result.departments}
        assert names == {"Design"}

    def test_sort_order_worst_first(self):
        # Strategy: 1 absent. Design: 0 absent, 2 late. Production: 0 absent,
        # 0 late. Order should be Strategy (most absent) → Design (most late
        # among absent-tied) → Production.
        dept_map = {
            "1001": "Production",
            "1002": "Design",
            "1003": "Design",
            "1004": "Strategy",
        }
        punches = [
            punch("1001", 9, 0, 1),    # Production: on time
            punch("1002", 9, 30, 2),   # Design: late
            punch("1003", 9, 45, 3),   # Design: late
            # 1004 didn't punch → Strategy: absent
        ]
        result = build_departments_rollup(
            punches,
            RULE,
            DAY,
            NOW,
            dept_map,
            expected_emp_codes=frozenset(dept_map.keys()),
        )
        order = [r.name for r in result.departments]
        assert order == ["Strategy", "Design", "Production"]

    def test_unassigned_bucket_for_employees_without_department(self):
        dept_map = {"1001": ""}  # explicit empty = no department in Odoo
        punches = [punch("1001", 9, 0, 1)]
        result = build_departments_rollup(
            punches,
            RULE,
            DAY,
            NOW,
            dept_map,
            expected_emp_codes=frozenset({"1001"}),
        )
        assert result.departments[0].name == "Unassigned"

    def test_empty_when_no_department_map(self):
        result = build_departments_rollup(
            punches=[],
            rule=RULE,
            day=DAY,
            now=NOW,
            department_by_emp_code={},
            expected_emp_codes=frozenset({"1001"}),
        )
        assert result.departments == []

    def test_empty_when_no_odoo_roster(self):
        # Without expected_emp_codes we can't compute a sensible denominator.
        result = build_departments_rollup(
            punches=[punch("1001", 9, 0, 1)],
            rule=RULE,
            day=DAY,
            now=NOW,
            department_by_emp_code={"1001": "Design"},
            expected_emp_codes=None,
        )
        assert result.departments == []

    def test_wfh_day_zeros_late_and_absent_but_keeps_present(self):
        # Thursday is WFH. Even with a late punch and a non-puncher, the
        # rollup should show present=1, late=0, absent=0 for the working
        # department.
        dept_map = {"1001": "Design", "1002": "Design"}
        # 1001 punches late at 09:45; 1002 doesn't punch.
        thursday_punches = [
            punch_on(THURSDAY, "1001", 9, 45, 1),
        ]
        result = build_departments_rollup(
            thursday_punches,
            WFH_RULE,
            THURSDAY,
            NOW_THURS,
            dept_map,
            expected_emp_codes=frozenset({"1001", "1002"}),
        )
        design = next(r for r in result.departments if r.name == "Design")
        assert design.late == 0
        assert design.absent == 0
        assert design.present == 1
        assert design.expected == 2

    def test_working_day_filter_narrows_universe(self):
        # 1003 is on a Mon–Fri schedule that doesn't include today — they
        # should drop out of the universe entirely.
        dept_map = {
            "1001": "Design",
            "1002": "Design",
            "1003": "Design",
        }
        result = build_departments_rollup(
            punches=[punch("1001", 9, 0, 1)],
            rule=RULE,
            day=DAY,
            now=NOW,
            department_by_emp_code=dept_map,
            expected_emp_codes=frozenset({"1001", "1002", "1003"}),
            working_emp_codes=frozenset({"1001", "1002"}),
        )
        design = next(r for r in result.departments if r.name == "Design")
        assert design.expected == 2  # 1003 dropped


def punch_on(day: date, emp_code: str, hh: int, mm: int, tid: int = 1):
    """Like the fixtures' punch() but parameterized by date for WFH tests."""
    from app.shared.models import Punch

    return Punch(
        transaction_id=tid,
        emp_code=emp_code,
        employee_name=None,
        punch_time=datetime(day.year, day.month, day.day, hh, mm),
        punch_state="0",
    )
