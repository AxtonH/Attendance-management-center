"""Tests for the Sunday-anchored week helper."""

from datetime import date

from app.shared.date_range import iter_days, week_range_for


class TestWeekRangeFor:
    def test_tuesday_anchors_to_preceding_sunday(self):
        # Example from the spec: Tue May 13 → Sun May 10–Sat May 16.
        start, end = week_range_for(date(2026, 5, 13))
        assert start == date(2026, 5, 10)
        assert end == date(2026, 5, 16)

    def test_sunday_is_its_own_start(self):
        start, end = week_range_for(date(2026, 5, 10))
        assert start == date(2026, 5, 10)
        assert end == date(2026, 5, 16)

    def test_saturday_anchors_to_preceding_sunday(self):
        start, end = week_range_for(date(2026, 5, 16))
        assert start == date(2026, 5, 10)
        assert end == date(2026, 5, 16)

    def test_each_weekday_resolves_consistently(self):
        # Every day of the same week must produce identical (start, end).
        ranges = {week_range_for(date(2026, 5, d)) for d in range(10, 17)}
        assert len(ranges) == 1

    def test_range_is_always_seven_days(self):
        start, end = week_range_for(date(2026, 5, 13))
        assert (end - start).days == 6  # inclusive: 7 calendar days


class TestIterDays:
    def test_full_week(self):
        days = iter_days(date(2026, 5, 10), date(2026, 5, 16))
        assert len(days) == 7
        assert days[0] == date(2026, 5, 10)
        assert days[-1] == date(2026, 5, 16)

    def test_single_day(self):
        days = iter_days(date(2026, 5, 13), date(2026, 5, 13))
        assert days == [date(2026, 5, 13)]
