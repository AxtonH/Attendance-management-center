"""Date-range helpers for multi-day views.

Pure functions, no I/O. Used by the weekly aggregation layer to determine
the calendar window for a given anchor day.
"""

from __future__ import annotations

from datetime import date, timedelta

# Sunday-anchored week (Prezlab convention, matches Sun–Thu Odoo schedules).
# Python's weekday(): Mon=0..Sun=6. Sunday's offset to itself is 0.
_SUNDAY_WEEKDAY = 6


def week_range_for(anchor: date) -> tuple[date, date]:
    """Return (start, end) for the Sunday-anchored week containing `anchor`.

    `end` is the inclusive last day (Saturday). To use this as a half-open
    range for query filters, add one day to `end`.

    Examples:
      Tue May 13 → (Sun May 10, Sat May 16)
      Sun May 10 → (Sun May 10, Sat May 16)
      Sat May 16 → (Sun May 10, Sat May 16)
    """
    # Days since the most recent Sunday. Python's weekday is 0=Mon..6=Sun,
    # so the formula needs a +1 to put Sunday at offset 0.
    days_since_sunday = (anchor.weekday() + 1) % 7
    start = anchor - timedelta(days=days_since_sunday)
    end = start + timedelta(days=6)
    return start, end


def iter_days(start: date, end: date) -> list[date]:
    """Inclusive list of dates from start to end."""
    span = (end - start).days
    return [start + timedelta(days=i) for i in range(span + 1)]


def month_range_for(anchor: date) -> tuple[date, date]:
    """Return (start, end) for the calendar month containing `anchor`.

    Start is always the 1st; end is the last day of that month (inclusive).
    Matches payroll cycles, expense reports, and how people think about
    months.

    Examples:
      Tue May 12 → (May 1, May 31)
      Sat Feb 29 (leap year) → (Feb 1, Feb 29)
      Sun Apr 30 → (Apr 1, Apr 30)
    """
    start = anchor.replace(day=1)
    # Last day of the month = day before the first of next month. Handles
    # December (year rollover) and leap-Feb without special-casing.
    if start.month == 12:
        next_month_start = start.replace(year=start.year + 1, month=1)
    else:
        next_month_start = start.replace(month=start.month + 1)
    end = next_month_start - timedelta(days=1)
    return start, end


__all__ = ["week_range_for", "month_range_for", "iter_days"]
