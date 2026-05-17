"""Tests for the weekly aggregation layer.

The week we'll fixture: Sun May 10 → Sat May 16 2026. May 14 is Thursday
(WFH per the default config); Saturday is off in the standard Sun–Thu
schedule. Both should suppress flags but not break tile math.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.features.dashboard.models import ExceptionTag
from app.features.dashboard.weekly import (
    build_weekly_arrivals,
    build_weekly_dashboard,
    build_weekly_departments_rollup,
    build_weekly_exceptions,
    build_weekly_overview,
)
from app.shared.date_range import iter_days, week_range_for
from app.shared.models import Employee, Punch, ShiftRule

# Wraps RULE with the WFH-Thursday convention from the production config.
RULE = ShiftRule(
    start="09:00",
    grace_minutes=15,
    full_day_minutes=480,
    wfh_weekdays=[3],
)

ANCHOR = date(2026, 5, 13)  # Tuesday → range is Sun May 10 to Sat May 16.
WEEK_DAYS = iter_days(*week_range_for(ANCHOR))

# `now` is well past grace_end on the anchor day, so per-day detectors
# treat the workweek as "already evaluated".
NOW = datetime(2026, 5, 16, 23, 0)


def _emp(code: str, name: str | None = None) -> Employee:
    return Employee(
        emp_code=code, name=name or f"Emp {code}", department="", active=True
    )


def _punch(emp_code: str, day: date, h: int, m: int, tid: int) -> Punch:
    return Punch(
        transaction_id=tid,
        emp_code=emp_code,
        employee_name=None,
        punch_time=datetime(day.year, day.month, day.day, h, m),
        punch_state="0",
    )


def _empty_week() -> dict[date, list[Punch]]:
    return {d: [] for d in WEEK_DAYS}


# ---------- Overview ----------


class TestWeeklyOverview:
    def test_present_counts_distinct_people_not_person_days(self):
        # 1001 punches Sun, Mon, Tue (3 days). 1002 punches Sun only.
        # Present = 2 distinct people, NOT 4 person-days.
        punches = _empty_week()
        punches[date(2026, 5, 10)] = [
            _punch("1001", date(2026, 5, 10), 9, 0, 1),
            _punch("1002", date(2026, 5, 10), 9, 0, 2),
        ]
        punches[date(2026, 5, 11)] = [_punch("1001", date(2026, 5, 11), 9, 0, 3)]
        punches[date(2026, 5, 12)] = [_punch("1001", date(2026, 5, 12), 9, 0, 4)]
        result = build_weekly_overview(
            punches,
            RULE,
            WEEK_DAYS,
            NOW,
            expected_emp_codes=frozenset({"1001", "1002"}),
        )
        assert result.present == 2

    def test_late_counts_each_late_day(self):
        # 1001 late twice (Sun, Mon), on time Tue. → late = 2.
        punches = _empty_week()
        punches[date(2026, 5, 10)] = [_punch("1001", date(2026, 5, 10), 9, 30, 1)]
        punches[date(2026, 5, 11)] = [_punch("1001", date(2026, 5, 11), 9, 30, 2)]
        punches[date(2026, 5, 12)] = [_punch("1001", date(2026, 5, 12), 9, 5, 3)]
        result = build_weekly_overview(
            punches,
            RULE,
            WEEK_DAYS,
            NOW,
            expected_emp_codes=frozenset({"1001"}),
        )
        assert result.late == 2

    def test_wfh_day_does_not_count_late(self):
        # Thursday is WFH: a 09:30 punch must not become a Late.
        punches = _empty_week()
        punches[date(2026, 5, 14)] = [_punch("1001", date(2026, 5, 14), 9, 30, 1)]
        result = build_weekly_overview(
            punches,
            RULE,
            WEEK_DAYS,
            NOW,
            expected_emp_codes=frozenset({"1001"}),
        )
        assert result.late == 0
        # Present still counted — they DID show up.
        assert result.present == 1

    def test_absent_sums_only_on_working_days(self):
        # 1001 never punches all week. Working days for Mon–Fri schedule:
        # Mon, Tue, Wed, Fri (Thursday is WFH → no absent). = 4 absences.
        # Saturday and Sunday are off, so not counted either.
        working = {
            date(2026, 5, 10): frozenset(),                # Sun: off
            date(2026, 5, 11): frozenset({"1001"}),         # Mon
            date(2026, 5, 12): frozenset({"1001"}),         # Tue
            date(2026, 5, 13): frozenset({"1001"}),         # Wed
            date(2026, 5, 14): frozenset({"1001"}),         # Thu (WFH suppresses)
            date(2026, 5, 15): frozenset({"1001"}),         # Fri
            date(2026, 5, 16): frozenset(),                # Sat: off
        }
        result = build_weekly_overview(
            _empty_week(),
            RULE,
            WEEK_DAYS,
            NOW,
            expected_emp_codes=frozenset({"1001"}),
            working_emp_codes_by_day=working,
        )
        assert result.absent == 4  # Mon, Tue, Wed, Fri

    def test_absent_is_none_without_odoo_roster(self):
        result = build_weekly_overview(_empty_week(), RULE, WEEK_DAYS, NOW)
        assert result.absent is None


# ---------- Department rollup ----------


class TestWeeklyDepartmentsRollup:
    def test_sums_person_days_per_department(self):
        punches = _empty_week()
        punches[date(2026, 5, 10)] = [
            _punch("1001", date(2026, 5, 10), 9, 0, 1),
            _punch("1002", date(2026, 5, 10), 9, 30, 2),
        ]
        punches[date(2026, 5, 11)] = [
            _punch("1001", date(2026, 5, 11), 9, 0, 3),
        ]
        dept_map = {"1001": "Design", "1002": "Design", "1003": "Strategy"}
        result = build_weekly_departments_rollup(
            punches,
            RULE,
            WEEK_DAYS,
            NOW,
            dept_map,
            expected_emp_codes=frozenset({"1001", "1002", "1003"}),
        )
        by_name = {r.name: r for r in result.departments}
        # Design: 3 people-days expected (1001×2 + 1002×2 across 2 working
        # days = depends on day weekday). With no working filter passed,
        # universe = full Odoo roster for every day. Strategy: same.
        assert "Design" in by_name
        assert by_name["Design"].present >= 3
        assert by_name["Design"].late >= 1  # 1002 was late on Sun

    def test_sort_worst_first_includes_absent_weight(self):
        # Two scheduled workdays for everyone (Sun, Mon).
        # Design's D1, D2 both punch in (late on Sun). Strategy's S1
        # never punches. Strategy ends up with absences; Design only late
        # → Strategy ranks above Design.
        only_sun_mon = {
            d: frozenset({"D1", "D2", "S1"})
            if d.weekday() in (6, 0)
            else frozenset()
            for d in WEEK_DAYS
        }
        punches = _empty_week()
        punches[date(2026, 5, 10)] = [
            _punch("D1", date(2026, 5, 10), 9, 30, 1),
            _punch("D2", date(2026, 5, 10), 9, 30, 2),
        ]
        punches[date(2026, 5, 11)] = [
            _punch("D1", date(2026, 5, 11), 9, 0, 3),
            _punch("D2", date(2026, 5, 11), 9, 0, 4),
        ]
        dept_map = {"D1": "Design", "D2": "Design", "S1": "Strategy"}
        result = build_weekly_departments_rollup(
            punches,
            RULE,
            WEEK_DAYS,
            NOW,
            dept_map,
            expected_emp_codes=frozenset({"D1", "D2", "S1"}),
            working_emp_codes_by_day=only_sun_mon,
        )
        names = [r.name for r in result.departments]
        assert names.index("Strategy") < names.index("Design")


# ---------- Arrivals ----------


class TestWeeklyArrivals:
    def test_employee_avg_is_bucketed(self):
        # 1001 punches at 09:00, 09:10, 09:20 → avg = 09:10 → in 09:00 bucket.
        punches = _empty_week()
        punches[date(2026, 5, 10)] = [_punch("1001", date(2026, 5, 10), 9, 0, 1)]
        punches[date(2026, 5, 11)] = [_punch("1001", date(2026, 5, 11), 9, 10, 2)]
        punches[date(2026, 5, 12)] = [_punch("1001", date(2026, 5, 12), 9, 20, 3)]
        result = build_weekly_arrivals(punches, WEEK_DAYS, bucket_minutes=15)
        by_label = {b.label: b.count for b in result.buckets}
        # 09:10 falls in [09:00, 09:15).
        assert by_label.get("09:00") == 1

    def test_only_days_with_punches_count_toward_average(self):
        # Same employee: punches only twice, at 09:00 and 09:30. Average 09:15
        # → falls in 09:15 bucket.
        punches = _empty_week()
        punches[date(2026, 5, 10)] = [_punch("1001", date(2026, 5, 10), 9, 0, 1)]
        punches[date(2026, 5, 12)] = [_punch("1001", date(2026, 5, 12), 9, 30, 2)]
        result = build_weekly_arrivals(punches, WEEK_DAYS, bucket_minutes=15)
        by_label = {b.label: b.count for b in result.buckets}
        assert by_label.get("09:15") == 1


# ---------- Exceptions ----------


class TestWeeklyExceptions:
    def test_groups_lateness_by_employee_with_day_chips(self):
        # 1001 late on Sun and Mon → one row with days=["Sun", "Mon"].
        punches = _empty_week()
        punches[date(2026, 5, 10)] = [_punch("1001", date(2026, 5, 10), 9, 30, 1)]
        punches[date(2026, 5, 11)] = [_punch("1001", date(2026, 5, 11), 9, 45, 2)]
        result = build_weekly_exceptions(
            employees=[_emp("1001", "Khaled")],
            punches_by_day=punches,
            rule=RULE,
            days=WEEK_DAYS,
            now=NOW,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "Khaled"},
        )
        late_rows = [i for i in result.items if i.tag == ExceptionTag.LATE]
        assert len(late_rows) == 1
        row = late_rows[0]
        assert row.emp_code == "1001"
        assert sorted(row.days or []) == ["Mon", "Sun"]
        # Multi-occurrence detail uses count form, not the per-day string.
        assert "2×" in row.detail

    def test_single_occurrence_keeps_original_detail(self):
        # One late day → detail should be the single-day "Late N min" string.
        punches = _empty_week()
        punches[date(2026, 5, 10)] = [_punch("1001", date(2026, 5, 10), 9, 30, 1)]
        result = build_weekly_exceptions(
            employees=[_emp("1001")],
            punches_by_day=punches,
            rule=RULE,
            days=WEEK_DAYS,
            now=NOW,
            expected_emp_codes=frozenset({"1001"}),
            roster_names={"1001": "K"},
        )
        late_rows = [i for i in result.items if i.tag == ExceptionTag.LATE]
        assert len(late_rows) == 1
        assert late_rows[0].detail.startswith("Late ")
        assert late_rows[0].days == ["Sun"]

    def test_filter_late_excludes_other_tags(self):
        # Mix of absent + late in the same week → filter pulls just lates.
        punches = _empty_week()
        punches[date(2026, 5, 11)] = [_punch("L1", date(2026, 5, 11), 9, 30, 1)]
        working = {
            d: frozenset({"L1", "A1"} if d.weekday() in (0, 1, 2, 3, 6) else set())
            for d in WEEK_DAYS
        }
        # Suppress Thursday (WFH) absences cleanly.
        result = build_weekly_exceptions(
            employees=[_emp("L1"), _emp("A1")],
            punches_by_day=punches,
            rule=RULE,
            days=WEEK_DAYS,
            now=NOW,
            filter_type="late",
            expected_emp_codes=frozenset({"L1", "A1"}),
            roster_names={"L1": "Late", "A1": "Absent"},
            working_emp_codes_by_day=working,
        )
        tags = {i.tag for i in result.items}
        assert tags == {ExceptionTag.LATE}


# ---------- Dashboard composite ----------


class TestWeeklyDashboard:
    def test_returns_weekly_mode_with_range(self):
        result = build_weekly_dashboard(
            employees=[],
            punches_by_day=_empty_week(),
            rule=RULE,
            days=WEEK_DAYS,
            now=NOW,
        )
        assert result.mode == "weekly"
        assert result.range_start == "2026-05-10"
        assert result.range_end == "2026-05-16"
