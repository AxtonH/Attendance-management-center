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


__all__ = ["week_range_for", "iter_days"]
