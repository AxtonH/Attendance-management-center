"""Pure functions that apply a ShiftRule to punch times.

No I/O, no datetime.now(): every function takes the values it needs as arguments.
That's what makes these trivially unit-testable.
"""

from datetime import date, datetime, time, timedelta

from app.shared.models import AttendanceStatus, ShiftRule


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def shift_start_dt(rule: ShiftRule, day: date) -> datetime:
    return datetime.combine(day, _parse_hhmm(rule.start))


def absent_cutoff_dt(rule: ShiftRule, day: date) -> datetime:
    return datetime.combine(day, _parse_hhmm(rule.absent_after))


def grace_end_dt(rule: ShiftRule, day: date) -> datetime:
    return shift_start_dt(rule, day) + timedelta(minutes=rule.grace_minutes)


def classify(
    first_punch: datetime | None,
    rule: ShiftRule,
    day: date,
    *,
    now: datetime,
) -> AttendanceStatus:
    """Return the attendance status for one employee on one day.

    - No punch yet and current time past absent cutoff: ABSENT
    - No punch yet and within working window: UNKNOWN (too early to call)
    - First punch within grace, or less than a full minute past it: PRESENT
    - First punch a full minute or more past grace: LATE

    Sub-minute lateness is treated as on-time. Otherwise we'd display
    "Late 0 min" rows for people who punched 30 seconds late, which reads as
    noise rather than signal.
    """
    if first_punch is None:
        return AttendanceStatus.ABSENT if now >= absent_cutoff_dt(rule, day) else AttendanceStatus.UNKNOWN

    return AttendanceStatus.LATE if minutes_late(first_punch, rule, day) >= 1 else AttendanceStatus.PRESENT


def minutes_late(first_punch: datetime, rule: ShiftRule, day: date) -> int:
    """Whole minutes past the grace window. Zero or negative means not late."""
    delta = first_punch - grace_end_dt(rule, day)
    return max(0, int(delta.total_seconds() // 60))
