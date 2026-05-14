from app.features.dashboard.models import ExceptionSeverity, ExceptionTag
from app.features.dashboard.service import (
    build_arrivals,
    build_dashboard,
    build_exceptions,
    build_overview,
)

from tests._fixtures import DAY, NOW, RULE, emp, punch


class TestOverview:
    def test_present_counts_everyone_who_punched(self):
        # Present = anyone with a punch (late or not). Late is a subset.
        employees = [emp("1001"), emp("1002")]
        punches = [punch("1001", 9, 5, 1), punch("1002", 9, 32, 2)]
        result = build_overview(employees, punches, RULE, DAY, NOW)
        assert result.present == 2
        assert result.late == 1
        assert result.absent is None

    def test_no_punches_returns_zero(self):
        result = build_overview([], [], RULE, DAY, NOW)
        assert result.present == 0
        assert result.late == 0
        assert result.absent is None

    def test_earliest_punch_wins(self):
        employees = [emp("1001")]
        punches = [punch("1001", 9, 30, 1), punch("1001", 8, 50, 2)]
        result = build_overview(employees, punches, RULE, DAY, NOW)
        assert result.present == 1
        assert result.late == 0


class TestExceptions:
    def test_late_employees_flagged(self):
        employees = [emp("1001"), emp("1002")]
        punches = [punch("1001", 9, 20, 1), punch("1002", 9, 45, 2)]
        result = build_exceptions(employees, punches, RULE, DAY, NOW)
        by_code = {i.emp_code: i for i in result.items}
        assert by_code["1001"].severity == ExceptionSeverity.LOW
        assert by_code["1002"].severity == ExceptionSeverity.MEDIUM
        assert all(i.tag == ExceptionTag.LATE for i in result.items)

    def test_sorted_by_minutes_late_descending(self):
        # 1001: 5 min late, 1002: 60 min, 1003: 20 min → order 1002, 1003, 1001.
        employees = [emp("1001"), emp("1002"), emp("1003")]
        punches = [punch("1001", 9, 20, 1), punch("1002", 10, 15, 2), punch("1003", 9, 35, 3)]
        result = build_exceptions(employees, punches, RULE, DAY, NOW)
        assert [i.emp_code for i in result.items] == ["1002", "1003", "1001"]

    def test_on_time_employees_not_flagged(self):
        employees = [emp("1001")]
        punches = [punch("1001", 9, 5, 1)]
        result = build_exceptions(employees, punches, RULE, DAY, NOW)
        assert result.total == 0

    def test_no_absent_rows_without_roster(self):
        # An employee in the list with no punch should NOT appear as absent.
        employees = [emp("1001"), emp("1002")]
        punches = [punch("1001", 9, 5, 1)]
        result = build_exceptions(employees, punches, RULE, DAY, NOW)
        assert all(i.tag == ExceptionTag.LATE for i in result.items)
        assert "1002" not in {i.emp_code for i in result.items}

    def test_filter_absent_returns_empty(self):
        employees = [emp("1001")]
        punches = [punch("1001", 9, 30, 1)]
        result = build_exceptions(employees, punches, RULE, DAY, NOW, filter_type="absent")
        assert result.total == 0


class TestArrivals:
    def test_buckets_first_punches(self):
        punches = [
            punch("1001", 8, 45, 1),
            punch("1002", 9, 5, 2),
            punch("1003", 9, 50, 3),
        ]
        result = build_arrivals(punches, DAY, bucket_minutes=30)
        by_label = {b.label: b.count for b in result.buckets}
        assert by_label["08:30"] == 1
        assert by_label["09:00"] == 1
        assert by_label["09:30"] == 1
        assert by_label["08:00"] == 0

    def test_auto_extends_past_latest_arrival(self):
        # Latest first-punch is 11:27; with 15-min buckets, last bucket label
        # should be 11:15 (the bucket covering 11:15-11:30).
        punches = [punch("1001", 8, 0, 1), punch("1002", 11, 27, 2)]
        result = build_arrivals(
            punches, DAY, bucket_minutes=15, window_start="07:30"
        )
        labels = [b.label for b in result.buckets]
        assert labels[-1] == "11:15"
        # Sanity: the late arrival lands in its bucket.
        by_label = {b.label: b.count for b in result.buckets}
        assert by_label["11:15"] == 1

    def test_respects_minimum_window_end(self):
        # Everyone arrives early — window still extends to the 10:30 floor.
        punches = [punch("1001", 8, 0, 1), punch("1002", 8, 30, 2)]
        result = build_arrivals(
            punches, DAY, bucket_minutes=15, window_start="07:30"
        )
        labels = [b.label for b in result.buckets]
        assert labels[-1] == "10:15"  # bucket covering 10:15-10:30

    def test_no_punches_uses_minimum_window(self):
        result = build_arrivals(
            [], DAY, bucket_minutes=15, window_start="07:30"
        )
        assert len(result.buckets) > 0
        assert result.buckets[0].label == "07:30"
        assert result.buckets[-1].label == "10:15"

    def test_explicit_window_end_still_honored(self):
        # If a caller passes window_end, the auto-extend is skipped.
        punches = [punch("1001", 11, 0, 1)]
        result = build_arrivals(
            punches, DAY, bucket_minutes=30, window_end="10:00"
        )
        labels = [b.label for b in result.buckets]
        assert "11:00" not in labels  # late punch not included


class TestDashboard:
    def test_aggregates_all_panels(self):
        employees = [emp("1001"), emp("1002")]
        punches = [punch("1001", 9, 5, 1), punch("1002", 9, 32, 2)]
        result = build_dashboard(employees, punches, RULE, DAY, NOW)
        assert result.overview.present == 2
        assert result.overview.late == 1
        assert result.exceptions.total == 1
        assert result.exceptions.items[0].emp_code == "1002"
        assert result.departments.departments == []
        assert sum(b.count for b in result.arrivals.buckets) == 2
