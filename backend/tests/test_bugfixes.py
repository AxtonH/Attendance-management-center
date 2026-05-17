"""Regression tests for two bugs reported on 2026-05-17.

Bug 1 — "Nouraldien on his day off":
  An employee came in to the office on Saturday (their scheduled day off)
  and got flagged for incomplete hours. Root cause: when an Odoo calendar
  id wasn't found in the cache, OdooCalendarRepository.working_days_for_calendar
  fell back to ALL_DAYS (every day = working day). That made Saturday a
  workday for that person. Fix: fall back to PREZLAB_DEFAULT_DAYS (Sun–Thu)
  instead. Still safe — covers 90% of Prezlab schedules — but doesn't
  silently turn the weekend into a workday.

Bug 2 — "29 absent in the tile, 0 in the panel":
  build_overview computed absent as `expected − punched` unconditionally,
  while detect_absent suppressed rows until `absent_after` (10:30). For
  90 minutes every morning the tile said N, the panel said 0. Fix: drop
  the separate absent_after threshold; use grace_end (09:15) for both
  paths so they always agree.
"""

from __future__ import annotations

from datetime import date, datetime

from app.features.dashboard.exceptions import (
    detect_absent,
    detect_prev_day_incomplete_hours,
)
from app.features.dashboard.service import build_overview
from app.infra.calendar_parser import PREZLAB_DEFAULT_DAYS
from app.infra.odoo_calendars import OdooCalendarRepository
from app.infra.odoo_client import OdooClient

from tests._fixtures import RULE, emp, punch


class TestUnknownCalendarFallsBackToPrezlabDefault:
    """Bug 1 regression: unknown calendar id must not become an all-days calendar."""

    def test_unknown_calendar_id_falls_back_to_sun_thu(self):
        class _Stub(OdooClient):
            def __init__(self) -> None:
                pass

            def search_read(self, *args, **kwargs):  # type: ignore[override]
                # Empty caches — nothing matches the calendar id we'll query.
                return []

        repo = OdooCalendarRepository(_Stub(), cache_ttl_seconds=60)
        days = repo.working_days_for_calendar(99999)
        assert days == PREZLAB_DEFAULT_DAYS
        # Saturday (weekday 5) must NOT be a working day under the fallback.
        assert 5 not in days

    def test_none_calendar_id_falls_back_to_sun_thu(self):
        class _Stub(OdooClient):
            def __init__(self) -> None:
                pass

            def search_read(self, *args, **kwargs):  # type: ignore[override]
                return []

        repo = OdooCalendarRepository(_Stub(), cache_ttl_seconds=60)
        days = repo.working_days_for_calendar(None)
        assert days == PREZLAB_DEFAULT_DAYS

    def test_employee_with_unknown_calendar_not_flagged_on_saturday(self):
        # End-to-end check at the detector level: a Saturday-only punch
        # for an employee whose calendar isn't in the Odoo cache must NOT
        # produce an incomplete-hours flag.
        from app.shared.models import Punch

        saturday = date(2026, 5, 16)  # 2026-05-16 is a Saturday
        prev_punches = [
            Punch(
                transaction_id=1,
                emp_code="999",
                employee_name="Nouraldien",
                punch_time=datetime(2026, 5, 16, 11, 0),
                punch_state="0",
            ),
            Punch(
                transaction_id=2,
                emp_code="999",
                employee_name="Nouraldien",
                punch_time=datetime(2026, 5, 16, 15, 3),
                punch_state="0",
            ),
        ]
        items = detect_prev_day_incomplete_hours(
            employees=[emp("999", "Nouraldien")],
            prev_punches=prev_punches,
            prev_day=saturday,
            rule=RULE,
            expected_emp_codes=frozenset({"999"}),
            roster_names={"999": "Nouraldien"},
            # Empty working set for Saturday — the route would compute this
            # from the now-fixed roster.working_emp_codes_for(saturday).
            working_emp_codes_prev_day=frozenset(),
        )
        assert items == []


class TestTilePanelAbsentAgreement:
    """Bug 2 regression: tile and panel must report the same absent count."""

    def test_pre_910am_tile_and_panel_both_show_zero(self):
        # Within the grace window (before 09:15) — nobody is provisionally
        # absent yet, and the panel agrees.
        day = date(2026, 5, 17)  # Sunday
        within_grace = datetime(2026, 5, 17, 9, 5)
        overview = build_overview(
            employees=[emp("1001"), emp("1002")],
            punches=[],
            rule=RULE,
            day=day,
            now=within_grace,
            expected_emp_codes=frozenset({"1001", "1002"}),
        )
        panel = detect_absent(
            employees=[emp("1001"), emp("1002")],
            first_punches={},
            rule=RULE,
            day=day,
            now=within_grace,
            expected_emp_codes=frozenset({"1001", "1002"}),
            roster_names={"1001": "A", "1002": "B"},
        )
        # Grace not yet ended → both report nothing.
        assert overview.absent == 0
        assert len(panel) == 0

    def test_just_past_grace_tile_and_panel_agree(self):
        # 09:16, one minute past grace_end. The tile previously showed 2,
        # the panel showed 0 (it was waiting until 10:30). They must agree.
        day = date(2026, 5, 17)  # Sunday
        past_grace = datetime(2026, 5, 17, 9, 16)
        overview = build_overview(
            employees=[emp("1001"), emp("1002")],
            punches=[],
            rule=RULE,
            day=day,
            now=past_grace,
            expected_emp_codes=frozenset({"1001", "1002"}),
        )
        panel = detect_absent(
            employees=[emp("1001"), emp("1002")],
            first_punches={},
            rule=RULE,
            day=day,
            now=past_grace,
            expected_emp_codes=frozenset({"1001", "1002"}),
            roster_names={"1001": "A", "1002": "B"},
        )
        assert overview.absent == 2
        assert len(panel) == 2

    def test_late_morning_tile_and_panel_still_agree(self):
        # 10:00 — well past grace, still well before the old 10:30 cutoff.
        day = date(2026, 5, 17)
        mid_morning = datetime(2026, 5, 17, 10, 0)
        # 1001 punched in (late), 1002 didn't.
        punches = [punch("1001", 9, 30, 1)]
        # Override the punch fixture's date so it lands on `day`.
        from app.shared.models import Punch as P

        punches = [
            P(
                transaction_id=1,
                emp_code="1001",
                employee_name=None,
                punch_time=datetime(2026, 5, 17, 9, 30),
                punch_state="0",
            )
        ]
        overview = build_overview(
            employees=[emp("1001"), emp("1002")],
            punches=punches,
            rule=RULE,
            day=day,
            now=mid_morning,
            expected_emp_codes=frozenset({"1001", "1002"}),
        )
        # Build first_punches for the panel detector.
        first_punches = {"1001": datetime(2026, 5, 17, 9, 30)}
        panel = detect_absent(
            employees=[emp("1001"), emp("1002")],
            first_punches=first_punches,
            rule=RULE,
            day=day,
            now=mid_morning,
            expected_emp_codes=frozenset({"1001", "1002"}),
            roster_names={"1001": "A", "1002": "B"},
        )
        assert overview.absent == 1
        assert {p.emp_code for p in panel} == {"1002"}
