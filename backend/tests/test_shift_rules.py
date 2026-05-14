from datetime import date, datetime

from app.shared.models import AttendanceStatus, ShiftRule
from app.shared.shift_rules import classify, minutes_late

RULE = ShiftRule(start="09:00", grace_minutes=15, absent_after="10:30")
DAY = date(2026, 5, 12)


def at(h: int, m: int) -> datetime:
    return datetime(2026, 5, 12, h, m)


class TestClassify:
    def test_on_time_at_start(self):
        assert classify(at(9, 0), RULE, DAY, now=at(11, 0)) == AttendanceStatus.PRESENT

    def test_on_time_within_grace(self):
        assert classify(at(9, 14), RULE, DAY, now=at(11, 0)) == AttendanceStatus.PRESENT

    def test_on_time_at_grace_boundary(self):
        # Exactly grace_end is still on-time (inclusive boundary).
        assert classify(at(9, 15), RULE, DAY, now=at(11, 0)) == AttendanceStatus.PRESENT

    def test_sub_minute_late_treated_as_present(self):
        # 09:15:30 → less than a full minute past grace → Present, not "Late 0 min".
        sub_minute = datetime(2026, 5, 12, 9, 15, 30)
        assert classify(sub_minute, RULE, DAY, now=at(11, 0)) == AttendanceStatus.PRESENT

    def test_late_at_one_full_minute_past_grace(self):
        assert classify(at(9, 16), RULE, DAY, now=at(11, 0)) == AttendanceStatus.LATE

    def test_late_much_later(self):
        assert classify(at(10, 45), RULE, DAY, now=at(11, 0)) == AttendanceStatus.LATE

    def test_absent_when_no_punch_and_past_cutoff(self):
        assert classify(None, RULE, DAY, now=at(10, 31)) == AttendanceStatus.ABSENT

    def test_unknown_when_no_punch_and_before_cutoff(self):
        assert classify(None, RULE, DAY, now=at(9, 30)) == AttendanceStatus.UNKNOWN

    def test_early_arrival_is_present(self):
        assert classify(at(8, 30), RULE, DAY, now=at(11, 0)) == AttendanceStatus.PRESENT


class TestMinutesLate:
    def test_zero_when_within_grace(self):
        assert minutes_late(at(9, 10), RULE, DAY) == 0

    def test_one_minute_after_grace(self):
        assert minutes_late(at(9, 16), RULE, DAY) == 1

    def test_thirty_minutes_after_grace(self):
        assert minutes_late(at(9, 45), RULE, DAY) == 30
