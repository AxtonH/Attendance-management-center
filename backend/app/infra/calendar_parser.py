"""Parse Odoo `resource.calendar` display names into sets of working weekdays.

Weekday numbering matches Python's `datetime.weekday()` and Odoo's
`resource.calendar.attendance.dayofweek`: Monday=0 ... Sunday=6.

Known calendar-name shapes (the working part lives between the first and
second `|` segments):
- "JO & KSA | Sun - Thu | Day Shift"           → range
- "JO & KSA | Mon, Wed, Thu | Day Shift"       → comma list
- "Standard 40 hours/week"                     → no pipes → Prezlab default

Subject to change. We fail OPEN: anything we can't parse is treated as
"every day is a working day", which over-flags weekends rather than
silently missing real absences on workdays.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

ALL_DAYS: frozenset[int] = frozenset(range(7))
# Prezlab's standard work week: Sun–Thu = {6, 0, 1, 2, 3}.
PREZLAB_DEFAULT_DAYS: frozenset[int] = frozenset({0, 1, 2, 3, 6})

_DAY_NAMES: dict[str, int] = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "weds": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


def _normalize_token(token: str) -> int | None:
    """Best-effort day-name → weekday number. None if unrecognized."""
    return _DAY_NAMES.get(token.strip().lower())


def _expand_range(start: int, end: int) -> frozenset[int]:
    """Inclusive weekday range, wrapping past Sunday (Sun=6 → Mon=0 wraps)."""
    if start <= end:
        return frozenset(range(start, end + 1))
    # Wrap: e.g. Fri(4)→Tue(1) means {4,5,6,0,1}.
    return frozenset(list(range(start, 7)) + list(range(0, end + 1)))


def _parse_working_segment(segment: str) -> frozenset[int] | None:
    """Parse the bit between pipes. Returns None if it doesn't look like days."""
    segment = segment.strip()

    # Range: "Sun - Thu", "Mon - Fri".
    range_match = re.match(
        r"^([A-Za-z]+)\s*-\s*([A-Za-z]+)$", segment
    )
    if range_match:
        start = _normalize_token(range_match.group(1))
        end = _normalize_token(range_match.group(2))
        if start is not None and end is not None:
            return _expand_range(start, end)

    # Comma list: "Mon, Wed, Thu".
    if "," in segment:
        tokens = [t for t in segment.split(",") if t.strip()]
        days = {_normalize_token(t) for t in tokens}
        if days and None not in days:
            return frozenset(d for d in days if d is not None)

    return None


def parse_working_days(calendar_name: str) -> frozenset[int]:
    """Return the set of weekdays the calendar covers.

    Precedence:
      1. Pipe-delimited day segment ("| Sun - Thu |" or "| Mon, Wed, Thu |").
      2. No pipes / unparseable → Prezlab default (Sun–Thu).
      3. Empty string / falsy → Prezlab default.

    Never returns an empty set. We log a warning when the name didn't parse
    so unknown patterns surface for the parser to be extended.
    """
    if not calendar_name or not calendar_name.strip():
        return PREZLAB_DEFAULT_DAYS

    parts = [p.strip() for p in calendar_name.split("|")]
    # Walk middle segments (skip first = region/country, last = shift label).
    # Calendars with just one segment fall through to default.
    for segment in parts[1:-1] if len(parts) >= 3 else []:
        days = _parse_working_segment(segment)
        if days is not None:
            return days

    # If we get here, we either had no pipes or no segment that looked like
    # weekdays. Fall back rather than fail closed.
    logger.info(
        "Calendar name %r didn't parse to weekdays — falling back to Sun–Thu",
        calendar_name,
    )
    return PREZLAB_DEFAULT_DAYS
