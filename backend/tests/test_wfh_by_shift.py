"""Shift-based WFH: Thu/Fri/Sat are WFH for whoever's shift covers them.

Covers the config rule (`default_shift.wfh_weekdays`) and `wfh_by_shift`
overrides, the roster's per-day resolution, and per-employee suppression
across the dashboard, Employees, and report paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.features.dashboard.exceptions import (
    detect_prev_day_incomplete_hours,
    detect_prev_day_missing_punch,
)
from app.features.dashboard.models import ExceptionTag
from app.features.dashboard.service import (
    build_departments_rollup,
    build_exceptions,
    build_overview,
)
from app.features.dashboard.weekly import build_weekly_overview
from app.features.employees.models import (
    EmployeesWeekResponse,
    EmployeeWeek,
    EmployeeWeekDay,
)
from app.features.employees.service import (
    build_employees_today,
    build_employees_week,
)
from app.features.exports.excel import render_xlsx
from app.features.exports.pdf import render_pdf
from app.features.exports.report import (
    DASH,
    STATUS_PRESENT,
    STATUS_UPCOMING,
    STATUS_WEEKEND,
    STATUS_WFH,
    build_attendance_report,
)
from app.infra.roster import (
    OdooRosterProvider,
    PunchDerivedRosterProvider,
    build_wfh_policy,
)
from app.shared.models import Punch, ShiftRule

# The real config file, so a broken production rule fails the suite.
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
SUN_THU = frozenset({SUN, MON, TUE, WED, THU})
MON_FRI = frozenset({MON, TUE, WED, THU, FRI})
TUE_SAT = frozenset({TUE, WED, THU, FRI, SAT})
WED_SUN = frozenset({WED, THU, FRI, SAT, SUN})
SAT_WED = frozenset({SAT, SUN, MON, TUE, WED})
FRI_TUE = frozenset({FRI, SAT, SUN, MON, TUE})

# Sun 10 → Sat 16 May 2026, one Prezlab week.
WEEK = [date(2026, 5, d) for d in range(10, 17)]
SUN_D, MON_D, TUE_D, WED_D, THU_D, FRI_D, SAT_D = WEEK
NOW_FRI = datetime(2026, 5, 15, 11, 0)  # past Friday's 09:15 cutoff

# Same WFH weekdays as production `default_shift`.
RULE = ShiftRule(start="09:00", grace_minutes=15, wfh_weekdays=[THU, FRI, SAT])


def _p(code: str, d: date, hh: int, mm: int, tid: int) -> Punch:
    return Punch(
        transaction_id=tid,
        emp_code=code,
        employee_name=None,
        punch_time=datetime(d.year, d.month, d.day, hh, mm),
    )


# ---------- Roster fakes ----------


class _FakeEmployees:
    def __init__(self, calendar_ids: Mapping[str, int | None]) -> None:
        self._calendar_ids = calendar_ids

    def calendar_ids(self) -> Mapping[str, int | None]:
        return self._calendar_ids


class _FakeCalendars:
    def __init__(self, days_by_calendar: Mapping[int, frozenset[int]]) -> None:
        self._days = days_by_calendar

    def working_days_for_calendar(self, calendar_id: int) -> frozenset[int]:
        return self._days[calendar_id]


def _roster() -> OdooRosterProvider:
    """One employee per shift pattern, plus one with no calendar (Sun–Thu)."""
    return OdooRosterProvider(
        odoo_employees=_FakeEmployees(  # type: ignore[arg-type]
            {"st": 1, "mf": 2, "ts": 3, "sw": 4, "ft": 5, "ws": 6, "none": None}
        ),
        odoo_calendars=_FakeCalendars(  # type: ignore[arg-type]
            {1: SUN_THU, 2: MON_FRI, 3: TUE_SAT, 4: SAT_WED, 5: FRI_TUE, 6: WED_SUN}
        ),
        fallback=PunchDerivedRosterProvider(CONFIG_DIR),
    )


# ---------- Config rule ----------


class TestPolicyConfig:
    def test_production_rule_is_thu_fri_sat_within_each_shift(self):
        policy = PunchDerivedRosterProvider(CONFIG_DIR).wfh_policy()
        assert policy.wfh_weekdays_for(SUN_THU) == {THU}
        assert policy.wfh_weekdays_for(MON_FRI) == {THU, FRI}
        assert policy.wfh_weekdays_for(TUE_SAT) == {THU, FRI, SAT}
        assert policy.wfh_weekdays_for(WED_SUN) == {THU, FRI, SAT}
        assert policy.wfh_weekdays_for(SAT_WED) == {SAT}
        assert policy.wfh_weekdays_for(FRI_TUE) == {FRI, SAT}
        # A part-time Mon/Wed/Thu calendar keeps its Thursday.
        assert policy.wfh_weekdays_for(frozenset({MON, WED, THU})) == {THU}

    def test_override_pins_one_shift_and_leaves_the_rest_on_the_rule(self):
        policy = build_wfh_policy({"Sun - Thu": []}, [THU, FRI, SAT])
        assert policy.wfh_weekdays_for(SUN_THU) == frozenset()
        assert policy.wfh_weekdays_for(MON_FRI) == {THU, FRI}

    @pytest.mark.parametrize(
        ("table", "message"),
        [
            ({"Sun - Thurz": ["Thu"]}, "can't parse shift"),
            ({"Sun - Thu": ["Thurz"]}, "unknown day"),
            ({"Sun - Thu": ["Fri"]}, "inside the shift"),
            ({"Sun - Thu": "Thu"}, "must be a list"),
            (
                {"Sun - Thu": ["Thu"], "Sun, Mon, Tue, Wed, Thu": ["Thu"]},
                "listed twice",
            ),
        ],
    )
    def test_bad_override_fails_loudly(self, table, message):
        with pytest.raises(ValueError, match=message):
            build_wfh_policy(table, [THU, FRI, SAT])


# ---------- Roster resolution ----------


class TestRosterResolution:
    def test_wfh_sets_per_day(self):
        roster = _roster()
        assert roster.wfh_emp_codes_for(THU_D) == {"st", "mf", "ts", "ws", "none"}
        assert roster.wfh_emp_codes_for(FRI_D) == {"mf", "ts", "ws", "ft"}
        assert roster.wfh_emp_codes_for(SAT_D) == {"ts", "ws", "sw", "ft"}
        for office_day in (SUN_D, MON_D, TUE_D, WED_D):
            assert roster.wfh_emp_codes_for(office_day) == frozenset()

    def test_thu_fri_sat_outside_a_shift_stay_weekend(self):
        # Sat–Wed: Saturday is WFH, Thursday and Friday are off.
        roster = _roster()
        assert "sw" in roster.wfh_emp_codes_for(SAT_D)
        for off_day in (THU_D, FRI_D):
            assert "sw" not in roster.working_emp_codes_for(off_day)
            assert "sw" not in roster.wfh_emp_codes_for(off_day)

    def test_wfh_is_always_a_subset_of_working(self):
        roster = _roster()
        for d in WEEK:
            assert roster.wfh_emp_codes_for(d) <= roster.working_emp_codes_for(d)

    def test_punch_derived_roster_has_no_per_employee_wfh(self):
        assert PunchDerivedRosterProvider(CONFIG_DIR).wfh_emp_codes_for(THU_D) is None


# ---------- Per-employee suppression ----------

# The services honor per-employee WFH sets, so a day can be WFH for one
# person and an office day for another (e.g. via a `wfh_by_shift` override).
# These pin that mechanic with explicit sets: on Friday "home" is WFH and
# "office" is expected in.
EXPECTED = frozenset({"home", "office"})
WFH_FRI = frozenset({"home"})
NAMES = {"home": "Home Person", "office": "Office Person"}


class TestPerEmployeeDashboard:
    def test_absent_counts_only_the_office_employee(self):
        overview = build_overview(
            [], [], RULE, FRI_D, NOW_FRI,
            expected_emp_codes=EXPECTED,
            working_emp_codes=EXPECTED,
            wfh_emp_codes=WFH_FRI,
        )
        assert (overview.present, overview.late, overview.absent) == (0, 0, 1)

    def test_both_present_but_only_the_office_employee_is_late(self):
        punches = [_p("home", FRI_D, 10, 0, 1), _p("office", FRI_D, 10, 0, 2)]
        overview = build_overview(
            [], punches, RULE, FRI_D, NOW_FRI,
            expected_emp_codes=EXPECTED,
            working_emp_codes=EXPECTED,
            wfh_emp_codes=WFH_FRI,
        )
        assert (overview.present, overview.late, overview.absent) == (2, 1, 0)

    def test_exceptions_panel_flags_only_the_office_employee(self):
        result = build_exceptions(
            [], [_p("home", FRI_D, 10, 0, 1)], RULE, FRI_D, NOW_FRI,
            expected_emp_codes=EXPECTED,
            roster_names=NAMES,
            working_emp_codes=EXPECTED,
            wfh_emp_codes=WFH_FRI,
        )
        assert {(i.emp_code, i.tag) for i in result.items} == {
            ("office", ExceptionTag.ABSENT)
        }

    def test_department_rollup(self):
        result = build_departments_rollup(
            [], RULE, FRI_D, NOW_FRI, {"home": "Design", "office": "Design"},
            expected_emp_codes=EXPECTED,
            working_emp_codes=EXPECTED,
            wfh_emp_codes=WFH_FRI,
        )
        [row] = result.departments
        assert (row.expected, row.present, row.late, row.absent) == (2, 0, 0, 1)

    def test_prev_day_missing_punch_skips_the_wfh_employee(self):
        lone_punches = [_p("home", FRI_D, 9, 0, 1), _p("office", FRI_D, 9, 0, 2)]
        items = detect_prev_day_missing_punch(
            [], lone_punches, FRI_D,
            expected_emp_codes=EXPECTED,
            roster_names=NAMES,
            working_emp_codes_prev_day=EXPECTED,
            wfh_weekdays=RULE.wfh_weekdays,
            wfh_emp_codes_prev_day=WFH_FRI,
        )
        assert [i.emp_code for i in items] == ["office"]

    def test_prev_day_incomplete_hours_skips_the_wfh_employee(self):
        short_days = [
            _p("home", FRI_D, 9, 0, 1),
            _p("home", FRI_D, 13, 0, 2),
            _p("office", FRI_D, 9, 0, 3),
            _p("office", FRI_D, 13, 0, 4),
        ]
        items = detect_prev_day_incomplete_hours(
            [], short_days, FRI_D, RULE,
            expected_emp_codes=EXPECTED,
            roster_names=NAMES,
            working_emp_codes_prev_day=EXPECTED,
            wfh_emp_codes_prev_day=WFH_FRI,
        )
        assert [i.emp_code for i in items] == ["office"]

    def test_weekly_overview_uses_each_days_wfh_set(self):
        # Thu: only "home" works (WFH). Fri: both work, "home" WFH. No punches.
        overview = build_weekly_overview(
            {}, RULE, [THU_D, FRI_D], datetime(2026, 5, 16, 12, 0),
            expected_emp_codes=EXPECTED,
            working_emp_codes_by_day={THU_D: WFH_FRI, FRI_D: EXPECTED},
            wfh_emp_codes_by_day={THU_D: WFH_FRI, FRI_D: WFH_FRI},
        )
        assert overview.absent == 1  # "office" on Friday only


# ---------- Employees view ----------


class TestEmployeesView:
    def test_no_absent_row_for_the_wfh_employee(self):
        result = build_employees_today(
            [], [], FRI_D,
            expected_emp_codes=EXPECTED,
            roster_names=NAMES,
            rule=RULE,
            now=NOW_FRI,
            working_emp_codes=EXPECTED,
            wfh_emp_codes=WFH_FRI,
        )
        assert {(r.emp_code, r.absent) for r in result.rows} == {("office", True)}

    def test_leave_on_a_wfh_day_reads_as_leave(self):
        result = build_employees_today(
            [], [], FRI_D,
            expected_emp_codes=EXPECTED,
            roster_names=NAMES,
            rule=RULE,
            now=NOW_FRI,
            working_emp_codes=EXPECTED,
            on_leave_emp_codes=frozenset({"home"}),
            wfh_emp_codes=WFH_FRI,
        )
        rows = {r.emp_code: r for r in result.rows}
        assert rows["home"].on_leave and not rows["home"].absent

    def test_expected_days_follow_each_shift(self):
        roster = _roster()
        codes = frozenset({"st", "mf", "ts", "sw", "ft", "ws"})
        result = build_employees_week(
            employees=[],
            punches_by_day={},
            days=WEEK,
            expected_emp_codes=codes,
            roster_names={c: c.upper() for c in codes},
            rule=RULE,
            now=datetime(2026, 5, 17, 12, 0),
            working_emp_codes_by_day={d: roster.working_emp_codes_for(d) for d in WEEK},
            wfh_emp_codes_by_day={d: roster.wfh_emp_codes_for(d) for d in WEEK},
        )
        rows = {r.emp_code: r for r in result.rows}
        assert {c: r.expected_days for c, r in rows.items()} == {
            "st": 4,  # Sun–Wed in office, Thu WFH
            "mf": 3,  # Mon–Wed in office, Thu + Fri WFH
            "ts": 2,  # Tue–Wed in office, Thu–Sat WFH
            "ws": 2,  # Wed + Sun in office, Thu–Sat WFH
            "sw": 4,  # Sun–Wed in office, Sat WFH
            "ft": 3,  # Sun–Tue in office, Fri + Sat WFH
        }
        assert rows["mf"].expected_minutes == 3 * RULE.full_day_minutes
        # Absent only on office days: nothing logged for WFH days.
        assert [d.date for d in rows["mf"].days if d.absent] == [
            "2026-05-11", "2026-05-12", "2026-05-13",
        ]
        assert [d.date for d in rows["sw"].days if d.absent] == [
            "2026-05-10", "2026-05-11", "2026-05-12", "2026-05-13",
        ]


# ---------- Report ----------


def _wday(d: date, *, pin=None, pout=None, worked=None) -> EmployeeWeekDay:
    return EmployeeWeekDay(
        date=d.isoformat(), punch_in=pin, punch_out=pout, worked_minutes=worked
    )


def _office_day(d: date) -> EmployeeWeekDay:
    return _wday(
        d,
        pin=datetime(d.year, d.month, d.day, 9, 0),
        pout=datetime(d.year, d.month, d.day, 17, 0),
        worked=480,
    )


def _report(code: str, days: list[EmployeeWeekDay], *, generated_on: date):
    roster = _roster()
    row = EmployeeWeek(
        emp_code=code,
        name=f"{code.upper()} Person",
        days_worked=len(days),
        expected_days=0,
        total_worked_minutes=sum(d.worked_minutes or 0 for d in days),
        expected_minutes=0,
        days=days,
    )
    return build_attendance_report(
        EmployeesWeekResponse(
            range_start=WEEK[0].isoformat(), range_end=WEEK[-1].isoformat(), rows=[row]
        ),
        days=WEEK,
        rule=RULE,
        period_label="10-05-2026 to 16-05-2026",
        generated_on=generated_on,
        department_by_emp_code={},
        working_emp_codes_by_day={d: roster.working_emp_codes_for(d) for d in WEEK},
        wfh_emp_codes_by_day={d: roster.wfh_emp_codes_for(d) for d in WEEK},
    )


class TestReport:
    def test_mon_fri_employee_has_two_labeled_wfh_days(self):
        report = _report(
            "mf",
            [_office_day(d) for d in (MON_D, TUE_D, WED_D)],
            generated_on=date(2026, 5, 17),
        )
        section = report.sections[0]
        assert [line.status for line in section.days] == [
            STATUS_WEEKEND,  # Sun
            STATUS_PRESENT,
            STATUS_PRESENT,
            STATUS_PRESENT,
            STATUS_WFH,  # Thu
            STATUS_WFH,  # Fri
            STATUS_WEEKEND,  # Sat
        ]
        assert section.days_wfh == 2
        assert section.wfh_label == "Thu, Fri"
        assert section.schedule_label == "Mon – Fri"

    def test_sat_wed_employee_works_saturday_from_home(self):
        report = _report(
            "sw",
            [_office_day(d) for d in (SUN_D, MON_D, TUE_D, WED_D)],
            generated_on=date(2026, 5, 17),
        )
        section = report.sections[0]
        assert [line.status for line in section.days] == [
            STATUS_PRESENT,  # Sun
            STATUS_PRESENT,
            STATUS_PRESENT,
            STATUS_PRESENT,  # Wed
            STATUS_WEEKEND,  # Thu
            STATUS_WEEKEND,  # Fri
            STATUS_WFH,  # Sat
        ]
        assert section.days_wfh == 1
        assert section.wfh_label == "Sat"

    def test_wfh_days_after_the_report_date_are_upcoming(self):
        report = _report("mf", [], generated_on=THU_D)
        section = report.sections[0]
        assert section.days[4].status == STATUS_WFH  # Thu = report date
        assert section.days[5].status == STATUS_UPCOMING  # Fri hasn't happened
        assert section.days_wfh == 1
        # The label describes the shift, so it still names both days.
        assert section.wfh_label == "Thu, Fri"

    def test_office_visit_on_a_wfh_day_is_never_late_or_short(self):
        visit = _wday(
            FRI_D,
            pin=datetime(2026, 5, 15, 11, 0),
            pout=datetime(2026, 5, 15, 13, 0),
            worked=120,
        )
        report = _report("mf", [visit], generated_on=date(2026, 5, 17))
        section = report.sections[0]
        friday = section.days[5]
        assert (friday.status, friday.late_by, friday.missing_hours) == (
            STATUS_PRESENT, "", DASH,
        )
        assert section.missing_minutes == 0

    def test_renderers_label_the_wfh_figure_by_shift(self):
        report = _report(
            "mf",
            [_office_day(d) for d in (MON_D, TUE_D, WED_D)],
            generated_on=date(2026, 5, 17),
        )
        workbook = load_workbook(BytesIO(render_xlsx(report)))
        values = {
            cell.value
            for sheet in workbook.worksheets[1:]
            for row in sheet.iter_rows()
            for cell in row
        }
        assert "WFH days" in values
        assert "per shift: Thu, Fri" in values
        assert "Days from home" not in values
        assert render_pdf(report).startswith(b"%PDF")
