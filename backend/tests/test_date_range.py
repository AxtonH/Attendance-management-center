"""Tests for the date-range helpers."""

from datetime import date

from app.shared.date_range import iter_days, month_range_for, week_range_for


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


class TestMonthRangeFor:
    def test_mid_month_anchors_to_first_and_last(self):
        start, end = month_range_for(date(2026, 5, 12))
        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 31)

    def test_first_of_month(self):
        start, end = month_range_for(date(2026, 5, 1))
        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 31)

    def test_last_of_month(self):
        start, end = month_range_for(date(2026, 5, 31))
        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 31)

    def test_february_leap_year(self):
        # 2024 was a leap year — Feb has 29 days.
        start, end = month_range_for(date(2024, 2, 15))
        assert start == date(2024, 2, 1)
        assert end == date(2024, 2, 29)

    def test_february_non_leap_year(self):
        start, end = month_range_for(date(2026, 2, 15))
        assert start == date(2026, 2, 1)
        assert end == date(2026, 2, 28)

    def test_december_rolls_to_next_january(self):
        # Tests the year-rollover branch in the helper.
        start, end = month_range_for(date(2026, 12, 15))
        assert start == date(2026, 12, 1)
        assert end == date(2026, 12, 31)

    def test_month_with_thirty_days(self):
        start, end = month_range_for(date(2026, 4, 15))
        assert end == date(2026, 4, 30)
