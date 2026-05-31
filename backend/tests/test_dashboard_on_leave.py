"""On-leave employees are excluded from the dashboard's Absent universe.

The route layer subtracts the excused sets (on-leave, public holiday) from
each day's working (in-office) set via `exclude_excused`, then hands that
reduced set to the existing builders as `working_emp_codes`. So these tests
verify two things:

  1. `exclude_excused` does the subtraction (for one or more excused sets)
     and preserves the phase-1 `None` sentinel.
  2. Feeding an excused-reduced working set to `build_overview` /
     `build_exceptions` / `build_departments_rollup` drops the excused
     person from the Absent count, the Absent flags, AND the department
     rollup (count + expected denominator) — matching the route wiring.
"""

from __future__ import annotations

from app.features.dashboard.models import ExceptionTag
from app.features.dashboard.service import (
    build_departments_rollup,
    build_exceptions,
    build_overview,
)
from app.infra.roster import exclude_excused

from tests._fixtures import DAY, NOW, RULE, emp, punch

# DAY = Tue 2026-05-12, NOW = 11:00 (past the 09:15 cutoff).
ROSTER = frozenset({"1001", "1002", "1003"})
NAMES = {"1001": "Alice", "1002": "Bob", "1003": "Cara"}


class TestExcludeExcusedHelper:
    def test_subtracts_leave_from_working(self):
        working = frozenset({"1001", "1002", "1003"})
        assert exclude_excused(working, frozenset({"1002"})) == frozenset(
            {"1001", "1003"}
        )

    def test_subtracts_multiple_excused_sets(self):
        # Leave + holiday both removed in one call.
        working = frozenset({"1001", "1002", "1003"})
        assert exclude_excused(
            working, frozenset({"1002"}), frozenset({"1003"})
        ) == frozenset({"1001"})

    def test_none_working_preserved(self):
        # Phase-1 sentinel must survive untouched.
        assert exclude_excused(None, frozenset({"1002"})) is None

    def test_empty_or_none_excused_is_noop(self):
        working = frozenset({"1001"})
        assert exclude_excused(working, None) == working
        assert exclude_excused(working, frozenset()) == working
        assert exclude_excused(working, None, None) == working


class TestAbsentExcludesOnLeave:
    def test_overview_absent_drops_on_leave_person(self):
        # 1001 punched, 1002 + 1003 absent. 1002 is on leave → universe
        # excludes them, so Absent = 1 (just 1003), not 2.
        working = exclude_excused(ROSTER, frozenset({"1002"}))
        result = build_overview(
            employees=[emp("1001")],
            punches=[punch("1001", 9, 0, 1)],
            rule=RULE,
            day=DAY,
            now=NOW,
            expected_emp_codes=ROSTER,
            working_emp_codes=working,
        )
        assert result.present == 1
        assert result.absent == 1  # 1003 only; 1002 excused

    def test_exceptions_absent_flag_omits_on_leave_person(self):
        working = exclude_excused(ROSTER, frozenset({"1002"}))
        result = build_exceptions(
            employees=[emp("1001")],
            punches=[punch("1001", 9, 0, 1)],
            rule=RULE,
            day=DAY,
            now=NOW,
            expected_emp_codes=ROSTER,
            roster_names=NAMES,
            working_emp_codes=working,
        )
        absent_codes = {
            i.emp_code for i in result.items if i.tag == ExceptionTag.ABSENT
        }
        assert "1002" not in absent_codes  # on leave, not flagged
        assert "1003" in absent_codes  # genuinely absent

    def test_department_rollup_drops_on_leave_from_absent_and_expected(self):
        # All three in one department. 1001 present, 1002 on leave,
        # 1003 absent. Expected counts only in-office people (2), present 1,
        # absent 1.
        working = exclude_excused(ROSTER, frozenset({"1002"}))
        dept_map = {"1001": "Design", "1002": "Design", "1003": "Design"}
        result = build_departments_rollup(
            punches=[punch("1001", 9, 0, 1)],
            rule=RULE,
            day=DAY,
            now=NOW,
            department_by_emp_code=dept_map,
            expected_emp_codes=ROSTER,
            working_emp_codes=working,
        )
        row = next(r for r in result.departments if r.name == "Design")
        assert row.expected == 2  # 1002 not expected in office (on leave)
        assert row.present == 1
        assert row.absent == 1

    def test_overview_absent_drops_leave_and_holiday_together(self):
        # 1001 punched; 1002 on leave; 1003 on a public holiday. Both
        # excused → Absent = 0 (everyone accounted for).
        working = exclude_excused(
            ROSTER, frozenset({"1002"}), frozenset({"1003"})
        )
        result = build_overview(
            employees=[emp("1001")],
            punches=[punch("1001", 9, 0, 1)],
            rule=RULE,
            day=DAY,
            now=NOW,
            expected_emp_codes=ROSTER,
            working_emp_codes=working,
        )
        assert result.present == 1
        assert result.absent == 0
