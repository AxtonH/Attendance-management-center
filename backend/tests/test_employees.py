from datetime import date, datetime

from app.features.employees.service import (
    build_employees_today,
    build_employees_week,
)
from app.shared.date_range import iter_days, week_range_for
from app.shared.models import Employee, Punch

from tests._fixtures import DAY, emp, punch


class TestEmployeesToday:
    def test_first_and_last_punch(self):
        employees = [emp("1001", "Khaled"), emp("1002", "Layla")]
        punches = [
            punch("1001", 9, 5, 1),
            punch("1001", 17, 30, 2),
            punch("1002", 8, 45, 3),
        ]
        result = build_employees_today(employees, punches, DAY)
        rows = {r.emp_code: r for r in result.rows}
        assert rows["1001"].punch_in.hour == 9
        assert rows["1001"].punch_out is not None
        assert rows["1001"].punch_out.hour == 17
        # 09:05 → 17:30 = 8h25m = 505 minutes.
        assert rows["1001"].worked_minutes == 505
        assert rows["1002"].punch_in.hour == 8
        assert rows["1002"].punch_out is None
        # Single-punch day: no defensible duration to show.
        assert rows["1002"].worked_minutes is None

    def test_excludes_inactive_employees(self):
        employees = [
            Employee(emp_code="1001", name="Active", department="", active=True),
            Employee(emp_code="1002", name="Inactive", department="", active=False),
        ]
        punches = [punch("1001", 9, 0, 1), punch("1002", 9, 0, 2)]
        result = build_employees_today(employees, punches, DAY)
        codes = {r.emp_code for r in result.rows}
        assert codes == {"1001"}

    def test_empty_input_returns_empty(self):
        result = build_employees_today([], [], DAY)
        assert result.rows == []


# ---------- Weekly ----------

# Anchor: Tue 2026-05-12 → range Sun May 10 ... Sat May 16.
_WEEK_DAYS = iter_days(*week_range_for(date(2026, 5, 12)))


def _wpunch(emp_code: str, d: date, h: int, m: int, tid: int) -> Punch:
    return Punch(
        transaction_id=tid,
        emp_code=emp_code,
        employee_name=None,
        punch_time=datetime(d.year, d.month, d.day, h, m),
        punch_state="0",
    )


class TestEmployeesWeek:
    def test_one_parent_row_per_employee_with_daily_children(self):
        # 1001 punches Sun, Mon, Tue (3 days). 1002 punches only Sun.
        punches_by_day = {d: [] for d in _WEEK_DAYS}
        punches_by_day[date(2026, 5, 10)] = [
            _wpunch("1001", date(2026, 5, 10), 9, 0, 1),
            _wpunch("1001", date(2026, 5, 10), 17, 30, 2),
            _wpunch("1002", date(2026, 5, 10), 8, 45, 3),
        ]
        punches_by_day[date(2026, 5, 11)] = [
            _wpunch("1001", date(2026, 5, 11), 9, 5, 4),
            _wpunch("1001", date(2026, 5, 11), 17, 0, 5),
        ]
        punches_by_day[date(2026, 5, 12)] = [
            _wpunch("1001", date(2026, 5, 12), 9, 10, 6),
            _wpunch("1001", date(2026, 5, 12), 17, 0, 7),
        ]
        result = build_employees_week(
            employees=[emp("1001", "Omar"), emp("1002", "Sara")],
            punches_by_day=punches_by_day,
            days=_WEEK_DAYS,
        )
        by_code = {r.emp_code: r for r in result.rows}
        # 1001 has 3 child rows (Sun, Mon, Tue), 1002 has 1 (Sun).
        assert by_code["1001"].days_worked == 3
        assert len(by_code["1001"].days) == 3
        assert by_code["1002"].days_worked == 1
        assert len(by_code["1002"].days) == 1

    def test_weekly_total_sums_daily_worked_minutes(self):
        # 1001 works 8h25m, 7h55m, 7h50m = 24h10m = 1450 min.
        punches_by_day = {d: [] for d in _WEEK_DAYS}
        punches_by_day[date(2026, 5, 10)] = [
            _wpunch("1001", date(2026, 5, 10), 9, 0, 1),
            _wpunch("1001", date(2026, 5, 10), 17, 25, 2),  # 505 min
        ]
        punches_by_day[date(2026, 5, 11)] = [
            _wpunch("1001", date(2026, 5, 11), 9, 5, 3),
            _wpunch("1001", date(2026, 5, 11), 17, 0, 4),   # 475 min
        ]
        punches_by_day[date(2026, 5, 12)] = [
            _wpunch("1001", date(2026, 5, 12), 9, 10, 5),
            _wpunch("1001", date(2026, 5, 12), 17, 0, 6),   # 470 min
        ]
        result = build_employees_week(
            employees=[emp("1001", "Omar")],
            punches_by_day=punches_by_day,
            days=_WEEK_DAYS,
        )
        row = result.rows[0]
        assert row.total_worked_minutes == 505 + 475 + 470

    def test_single_punch_day_contributes_none_to_total(self):
        # Only one punch on Sun → worked_minutes None → total = 0.
        punches_by_day = {d: [] for d in _WEEK_DAYS}
        punches_by_day[date(2026, 5, 10)] = [
            _wpunch("1001", date(2026, 5, 10), 9, 0, 1),
        ]
        result = build_employees_week(
            employees=[emp("1001", "Omar")],
            punches_by_day=punches_by_day,
            days=_WEEK_DAYS,
        )
        row = result.rows[0]
        assert row.days_worked == 1
        assert row.days[0].worked_minutes is None
        assert row.total_worked_minutes == 0

    def test_off_days_are_not_in_child_list(self):
        # 1001 punches only Sun and Wed. No off-day rows should appear.
        punches_by_day = {d: [] for d in _WEEK_DAYS}
        punches_by_day[date(2026, 5, 10)] = [
            _wpunch("1001", date(2026, 5, 10), 9, 0, 1),
            _wpunch("1001", date(2026, 5, 10), 17, 0, 2),
        ]
        punches_by_day[date(2026, 5, 13)] = [
            _wpunch("1001", date(2026, 5, 13), 9, 0, 3),
            _wpunch("1001", date(2026, 5, 13), 17, 0, 4),
        ]
        result = build_employees_week(
            employees=[emp("1001", "Omar")],
            punches_by_day=punches_by_day,
            days=_WEEK_DAYS,
        )
        row = result.rows[0]
        assert row.days_worked == 2
        # Both child rows match a day the employee actually punched.
        dates = {d.date for d in row.days}
        assert dates == {"2026-05-10", "2026-05-13"}

    def test_employees_with_zero_punches_omitted(self):
        # 1002 never punched all week → must not appear in the response.
        punches_by_day = {d: [] for d in _WEEK_DAYS}
        punches_by_day[date(2026, 5, 10)] = [
            _wpunch("1001", date(2026, 5, 10), 9, 0, 1),
            _wpunch("1001", date(2026, 5, 10), 17, 0, 2),
        ]
        result = build_employees_week(
            employees=[emp("1001"), emp("1002")],
            punches_by_day=punches_by_day,
            days=_WEEK_DAYS,
        )
        codes = {r.emp_code for r in result.rows}
        assert codes == {"1001"}

    def test_response_carries_range_dates(self):
        result = build_employees_week(
            employees=[],
            punches_by_day={d: [] for d in _WEEK_DAYS},
            days=_WEEK_DAYS,
        )
        assert result.range_start == "2026-05-10"
        assert result.range_end == "2026-05-16"

    def test_expected_minutes_excludes_wfh_days(self):
        # Sun–Thu schedule with Thursday WFH means 4 in-office days × 8h
        # = 32h expected, not 40h. Critical for matching what Prezlab
        # actually tracks (Thursdays aren't recorded by BioTime).
        from app.shared.models import ShiftRule

        rule = ShiftRule(
            start="09:00",
            grace_minutes=15,
            full_day_minutes=480,
            wfh_weekdays=[3],  # Thursday
        )
        sun_thu = frozenset({"1001"})  # employee works Sun–Thu
        working_by_day = {
            d: sun_thu if d.weekday() in (0, 1, 2, 3, 6) else frozenset()
            for d in _WEEK_DAYS
        }
        # Employee punches one day so they appear in the response.
        punches_by_day = {d: [] for d in _WEEK_DAYS}
        punches_by_day[date(2026, 5, 10)] = [
            _wpunch("1001", date(2026, 5, 10), 9, 0, 1),
            _wpunch("1001", date(2026, 5, 10), 17, 0, 2),
        ]
        result = build_employees_week(
            employees=[emp("1001")],
            punches_by_day=punches_by_day,
            days=_WEEK_DAYS,
            rule=rule,
            working_emp_codes_by_day=working_by_day,
        )
        row = result.rows[0]
        # Sun, Mon, Tue, Wed are working in-office (4 days). Thursday WFH
        # is dropped. Sat/Fri are off. → 4 × 480 = 1920 minutes (32h).
        assert row.expected_days == 4
        assert row.expected_minutes == 4 * 480

    def test_expected_zero_without_rule(self):
        # Backwards-compatible: omitting rule/working data defaults
        # expecteds to 0 instead of crashing.
        punches_by_day = {d: [] for d in _WEEK_DAYS}
        punches_by_day[date(2026, 5, 10)] = [
            _wpunch("1001", date(2026, 5, 10), 9, 0, 1),
            _wpunch("1001", date(2026, 5, 10), 17, 0, 2),
        ]
        result = build_employees_week(
            employees=[emp("1001")],
            punches_by_day=punches_by_day,
            days=_WEEK_DAYS,
        )
        row = result.rows[0]
        assert row.expected_days == 0
        assert row.expected_minutes == 0

    def test_outer_sort_emp_code_desc_numeric(self):
        # Numeric codes sort descending: 1002 before 1001.
        punches_by_day = {d: [] for d in _WEEK_DAYS}
        punches_by_day[date(2026, 5, 10)] = [
            _wpunch("1001", date(2026, 5, 10), 9, 0, 1),
            _wpunch("1001", date(2026, 5, 10), 17, 0, 2),
            _wpunch("1002", date(2026, 5, 10), 9, 0, 3),
            _wpunch("1002", date(2026, 5, 10), 17, 0, 4),
        ]
        result = build_employees_week(
            employees=[emp("1001"), emp("1002")],
            punches_by_day=punches_by_day,
            days=_WEEK_DAYS,
        )
        assert [r.emp_code for r in result.rows] == ["1002", "1001"]
