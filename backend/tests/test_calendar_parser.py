"""Tests for the calendar-name parser. Mon=0..Sun=6 throughout."""

from app.infra.calendar_parser import (
    ALL_DAYS,
    PREZLAB_DEFAULT_DAYS,
    parse_working_days,
)


class TestPipeDelimitedRanges:
    def test_sun_thu(self):
        # Sun(6) wraps to Thu(3): {6,0,1,2,3}.
        assert parse_working_days("JO & KSA | Sun - Thu | Day Shift") == frozenset(
            {0, 1, 2, 3, 6}
        )

    def test_mon_fri(self):
        assert parse_working_days("JO & KSA | Mon - Fri | Day Shift A") == frozenset(
            {0, 1, 2, 3, 4}
        )

    def test_sat_wed(self):
        # Sat(5)→Wed(2) wraps: {5,6,0,1,2}.
        assert parse_working_days("JO & KSA | Sat - Wed | Day Shift") == frozenset(
            {5, 6, 0, 1, 2}
        )

    def test_fri_tue(self):
        # Fri(4)→Tue(1) wraps: {4,5,6,0,1}.
        assert parse_working_days("JO & KSA | Fri - Tue | Day Shift") == frozenset(
            {4, 5, 6, 0, 1}
        )

    def test_tue_sat(self):
        assert parse_working_days("JO & KSA | Tue - Sat | Day Shift") == frozenset(
            {1, 2, 3, 4, 5}
        )


class TestPipeDelimitedLists:
    def test_three_explicit_days(self):
        assert parse_working_days(
            "JO & KSA | Mon, Wed, Thu | Day Shift"
        ) == frozenset({0, 2, 3})

    def test_handles_whitespace(self):
        assert parse_working_days(
            "JO & KSA |  Sun ,  Tue ,  Thu | Day Shift"
        ) == frozenset({6, 1, 3})


class TestFallbacks:
    def test_no_pipes_falls_back_to_prezlab_default(self):
        assert parse_working_days("Standard 40 hours/week") == PREZLAB_DEFAULT_DAYS

    def test_empty_string_returns_default(self):
        assert parse_working_days("") == PREZLAB_DEFAULT_DAYS

    def test_unknown_segment_pattern_returns_default(self):
        # New shape we haven't seen — must not raise, must not return empty.
        result = parse_working_days("Some New Region | Whatever | Custom")
        assert result == PREZLAB_DEFAULT_DAYS

    def test_unknown_day_token_returns_default(self):
        # Typo / mojibake — should fall back, not crash.
        result = parse_working_days("JO & KSA | Snu - Thu | Day Shift")
        assert result == PREZLAB_DEFAULT_DAYS


class TestSanity:
    def test_never_returns_empty(self):
        # If we ever return an empty set, employees on that calendar
        # would be flagged absent EVERY day. Don't.
        for name in [
            "",
            "weird",
            "| | |",
            "JO & KSA | not-a-day | Day Shift",
            "Sun - Thu",  # missing pipes
        ]:
            result = parse_working_days(name)
            assert len(result) > 0, f"empty result for {name!r}"

    def test_default_is_sun_thu(self):
        assert PREZLAB_DEFAULT_DAYS == frozenset({0, 1, 2, 3, 6})

    def test_all_days_is_full_week(self):
        assert ALL_DAYS == frozenset(range(7))
