"""Tests for the employee-attendance exports feature.

Covers three pure layers without spinning up the app (matches the repo's
service-level test convention):
  - the report builder (response models → AttendanceReport),
  - the route's pure helpers (range resolution, emp_codes parsing), and
  - the Excel/PDF renderers (produce well-formed bytes).
"""

from datetime import date, datetime

from app.features.employees.models import (
    EmployeesWeekResponse,
    EmployeeWeek,
    EmployeeWeekDay,
)
from app.features.exports.excel import render_xlsx
from app.features.exports.pdf import render_pdf
from app.features.exports.report import (
    STATUS_ABSENT,
    STATUS_DAY_OFF,
    STATUS_HOLIDAY,
    STATUS_LATE,
    STATUS_ON_LEAVE,
    STATUS_PRESENT,
    STATUS_UPCOMING,
    STATUS_WFH,
    build_attendance_report,
)
from app.features.exports.route import (
    _filename,
    _parse_emp_codes,
    _period_label,
    _resolve_range,
)
from app.shared.models import ShiftRule

_DAY = date(2026, 5, 12)

# Sun–Thu week, Thursday WFH — the org default shape.
_RULE = ShiftRule(start="09:00", grace_minutes=15, wfh_weekdays=[3])


def _wday(
    iso: str,
    *,
    pin: datetime | None = None,
    pout: datetime | None = None,
    worked: int | None = None,
    absent: bool = False,
    on_leave: bool = False,
    on_holiday: bool = False,
) -> EmployeeWeekDay:
    return EmployeeWeekDay(
        date=iso,
        punch_in=pin,
        punch_out=pout,
        worked_minutes=worked,
        absent=absent,
        on_leave=on_leave,
        on_holiday=on_holiday,
    )


def _week(code: str, name: str, days: list[EmployeeWeekDay]) -> EmployeeWeek:
    worked = [d for d in days if not (d.absent or d.on_leave or d.on_holiday)]
    return EmployeeWeek(
        emp_code=code,
        name=name,
        days_worked=len(worked),
        expected_days=0,
        total_worked_minutes=sum(d.worked_minutes or 0 for d in worked),
        expected_minutes=0,
        days=days,
    )


def _response(rows: list[EmployeeWeek]) -> EmployeesWeekResponse:
    return EmployeesWeekResponse(
        range_start="2026-05-10", range_end="2026-05-13", rows=rows
    )


# Sun 10 → Wed 13 May 2026.
_DAYS = [date(2026, 5, 10), date(2026, 5, 11), date(2026, 5, 12), date(2026, 5, 13)]


def _build(rows, **kwargs):
    defaults = dict(
        days=_DAYS,
        rule=_RULE,
        period_label="10-05-2026 to 13-05-2026",
        generated_on=date(2026, 5, 14),
        department_by_emp_code={},
    )
    defaults.update(kwargs)
    return build_attendance_report(_response(rows), **defaults)


# ---------- Report builder: day statuses ----------


class TestDayStatuses:
    def test_on_time_late_absent_and_excused(self):
        days = [
            _wday(
                "2026-05-10",
                pin=datetime(2026, 5, 10, 9, 5),
                pout=datetime(2026, 5, 10, 17, 0),
                worked=475,
            ),
            _wday(
                "2026-05-11",
                pin=datetime(2026, 5, 11, 9, 40),
                pout=datetime(2026, 5, 11, 17, 0),
                worked=440,
            ),
            _wday("2026-05-12", absent=True),
            _wday("2026-05-13", on_leave=True),
        ]
        report = _build([_week("1001", "Khaled", days)])
        section = report.sections[0]
        statuses = [line.status for line in section.days]
        assert statuses == [
            STATUS_PRESENT,  # 09:05 is within 09:00+15m grace
            STATUS_LATE,  # 09:40 → 25m past grace
            STATUS_ABSENT,
            STATUS_ON_LEAVE,
        ]
        assert section.days[1].late_by == "25m"
        assert section.days[0].late_by == ""

    def test_holiday_wins_and_no_late_on_wfh_weekday(self):
        # Thu 2026-05-14 is weekday 3 (WFH); a late-looking punch there
        # must not read as Late.
        days_in_period = [date(2026, 5, 13), date(2026, 5, 14)]
        rows = [
            _week(
                "1",
                "A",
                [
                    _wday("2026-05-13", on_leave=True, on_holiday=True),
                    _wday(
                        "2026-05-14",
                        pin=datetime(2026, 5, 14, 11, 0),
                        pout=datetime(2026, 5, 14, 17, 0),
                        worked=360,
                    ),
                ],
            )
        ]
        report = _build(rows, days=days_in_period)
        statuses = [line.status for line in report.sections[0].days]
        assert statuses == [STATUS_HOLIDAY, STATUS_PRESENT]

    def test_gap_days_day_off_wfh_and_upcoming(self):
        # Employee has no rows at all: Sun is their day off (schedule says
        # not working), Mon has no schedule info (upcoming/no-data), Tue has
        # schedule info and they're working (still upcoming — the employees
        # service emits absent rows only once settled), Wed... use Thu-like
        # WFH via rule weekday 3 → 2026-05-13 is Wednesday (weekday 2), so
        # check WFH on 2026-05-14 in a dedicated period.
        days_in_period = [date(2026, 5, 10), date(2026, 5, 11), date(2026, 5, 14)]
        working = {
            date(2026, 5, 10): frozenset({"other"}),  # not scheduled → day off
            date(2026, 5, 11): None,  # no schedule info
            date(2026, 5, 14): frozenset({"1"}),  # scheduled, WFH weekday
        }
        report = _build(
            [_week("1", "A", [])],
            days=days_in_period,
            working_emp_codes_by_day=working,
        )
        statuses = [line.status for line in report.sections[0].days]
        assert statuses == [STATUS_DAY_OFF, STATUS_UPCOMING, STATUS_WFH]


# ---------- Report builder: per-employee stats ----------


class TestEmployeeStats:
    def test_counts_averages_and_attendance_pct(self):
        days = [
            _wday(
                "2026-05-10",
                pin=datetime(2026, 5, 10, 9, 0),
                pout=datetime(2026, 5, 10, 17, 0),
                worked=480,
            ),
            _wday(
                "2026-05-11",
                pin=datetime(2026, 5, 11, 10, 0),  # late, and no sign-out
            ),
            _wday("2026-05-12", absent=True),
            _wday("2026-05-13", on_leave=True),
        ]
        section = _build([_week("1001", "Khaled", days)]).sections[0]
        assert section.days_attended == 2
        assert section.days_late == 1
        assert section.days_absent == 1
        assert section.days_on_leave == 1
        assert section.days_expected == 3  # attended + absent, leave excluded
        assert section.missing_signouts == 1
        assert section.avg_arrival == "09:30"  # mean of 09:00 and 10:00
        assert section.total_worked == "8h 00m"
        assert section.attendance_pct == "67%"

    def test_department_resolved_from_map(self):
        report = _build(
            [_week("1001", "Khaled", [])],
            department_by_emp_code={"1001": "Animation"},
        )
        assert report.sections[0].department == "Animation"
        # Overview row carries it too (col 1 = Department).
        assert report.overview_rows[0][1] == "Animation"


# ---------- Report builder: selection + ordering + summary ----------


class TestReportShape:
    def test_emp_codes_selection_filters_sections_and_stats(self):
        rows = [
            _week("1", "Alia", [_wday("2026-05-12", absent=True)]),
            _week("2", "Basel", [_wday("2026-05-12", absent=True)]),
        ]
        report = _build(rows, emp_codes=frozenset({"2"}))
        assert [s.name for s in report.sections] == ["Basel"]
        # Summary "Employees" stat reflects the selection, not the response.
        assert report.stats[0].label == "Employees"
        assert report.stats[0].value == "1"

    def test_sections_sorted_by_name(self):
        rows = [
            _week("9", "zaid", []),
            _week("1", "Alia", []),
            _week("5", "Basel", []),
        ]
        report = _build(rows)
        assert [s.name for s in report.sections] == ["Alia", "Basel", "zaid"]
        assert [r[0] for r in report.overview_rows] == ["Alia", "Basel", "zaid"]

    def test_overview_rows_align_to_columns(self):
        report = _build([_week("1", "Alia", [])])
        assert len(report.overview_rows[0]) == len(report.overview_columns)

    def test_empty_report(self):
        report = _build([])
        assert report.sections == []
        assert report.overview_rows == []
        assert report.stats[0].value == "0"
        assert report.arrival_histogram == []

    def test_arrival_histogram_buckets_with_gaps(self):
        # Arrivals at 08:55, 09:05, 09:10, 10:05 → 30-min buckets 08:30,
        # 09:00, (empty 09:30), 10:00. Empty middle buckets are kept so
        # the shape reads correctly.
        rows = [
            _week(
                "1",
                "A",
                [
                    _wday("2026-05-10", pin=datetime(2026, 5, 10, 8, 55)),
                    _wday("2026-05-11", pin=datetime(2026, 5, 11, 9, 5)),
                    _wday("2026-05-12", pin=datetime(2026, 5, 12, 9, 10)),
                    _wday("2026-05-13", pin=datetime(2026, 5, 13, 10, 5)),
                ],
            )
        ]
        report = _build(rows)
        bins = [(b.label, b.count) for b in report.arrival_histogram]
        assert bins == [("08:30", 1), ("09:00", 2), ("09:30", 0), ("10:00", 1)]


# ---------- Route helpers ----------


class TestResolveRange:
    def test_daily_is_single_day(self):
        assert _resolve_range("daily", _DAY, None, None) == (_DAY, _DAY, True)

    def test_weekly_expands_to_sun_sat(self):
        s, e, single = _resolve_range("weekly", _DAY, None, None)
        # Tue 2026-05-12 → Sun 2026-05-10 .. Sat 2026-05-16.
        assert (s, e) == (date(2026, 5, 10), date(2026, 5, 16))
        assert single is False

    def test_monthly_expands_to_calendar_month(self):
        s, e, single = _resolve_range("monthly", _DAY, None, None)
        assert (s, e) == (date(2026, 5, 1), date(2026, 5, 31))
        assert single is False

    def test_custom_uses_explicit_edges(self):
        s, e, single = _resolve_range(
            "custom", _DAY, date(2026, 5, 1), date(2026, 5, 7)
        )
        assert (s, e) == (date(2026, 5, 1), date(2026, 5, 7))
        assert single is False

    def test_custom_same_day_collapses_to_single(self):
        s, e, single = _resolve_range(
            "custom", _DAY, date(2026, 5, 3), date(2026, 5, 3)
        )
        assert (s, e, single) == (date(2026, 5, 3), date(2026, 5, 3), True)

    def test_custom_reversed_edges_are_swapped(self):
        s, e, single = _resolve_range(
            "custom", _DAY, date(2026, 5, 9), date(2026, 5, 1)
        )
        assert (s, e) == (date(2026, 5, 1), date(2026, 5, 9))
        assert single is False


class TestParseEmpCodes:
    def test_none_and_blank_mean_everyone(self):
        assert _parse_emp_codes(None) is None
        assert _parse_emp_codes("") is None
        assert _parse_emp_codes(" , ,") is None

    def test_csv_parses_and_strips(self):
        assert _parse_emp_codes("1001, 1002 ,1003") == frozenset(
            {"1001", "1002", "1003"}
        )


class TestFilenameAndLabel:
    def test_single_day_filename(self):
        assert (
            _filename(_DAY, _DAY, True, "xlsx")
            == "prezlab-attendance_2026-05-12.xlsx"
        )

    def test_range_filename(self):
        assert (
            _filename(date(2026, 6, 1), date(2026, 6, 30), False, "pdf")
            == "prezlab-attendance_2026-06-01_to_2026-06-30.pdf"
        )

    def test_single_day_label_is_ddmmyyyy(self):
        assert _period_label(_DAY, _DAY, True) == "Tuesday, 12-05-2026"

    def test_range_label_is_ddmmyyyy(self):
        assert (
            _period_label(date(2026, 6, 1), date(2026, 6, 30), False)
            == "01-06-2026 to 30-06-2026"
        )


# ---------- Renderers produce valid file bytes ----------


def _sample_report():
    days = [
        _wday(
            "2026-05-10",
            pin=datetime(2026, 5, 10, 9, 5),
            pout=datetime(2026, 5, 10, 17, 30),
            worked=505,
        ),
        _wday("2026-05-11", absent=True),
        _wday("2026-05-12", on_leave=True),
        _wday("2026-05-13", on_holiday=True),
    ]
    return _build(
        [
            _week("1001", "Khaled", days),
            # A name Excel can't take verbatim as a sheet title.
            _week("1002", "S/mith [Very Long Name Beyond The Sheet Cap]", days),
            # Duplicate name → dedupe suffix path.
            _week("1003", "Khaled", []),
        ],
        department_by_emp_code={"1001": "Animation"},
    )


class TestRenderers:
    def test_xlsx_has_zip_magic_and_summary_plus_person_sheets(self):
        data = render_xlsx(_sample_report())
        # .xlsx is a zip container → starts with "PK".
        assert data[:2] == b"PK"
        assert len(data) > 1000

        from io import BytesIO

        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(data))
        # Summary + one sheet per employee, all uniquely named.
        assert wb.sheetnames[0] == "Summary"
        assert len(wb.sheetnames) == 4
        assert len(set(wb.sheetnames)) == 4
        for name in wb.sheetnames:
            assert len(name) <= 31
            assert not any(ch in name for ch in "[]:*?/\\")

    def test_pdf_has_pdf_magic_and_nonzero_size(self):
        data = render_pdf(_sample_report())
        assert data[:5] == b"%PDF-"
        assert len(data) > 500

    def test_renderers_handle_empty_report(self):
        report = _build([])
        assert render_xlsx(report)[:2] == b"PK"
        assert render_pdf(report)[:5] == b"%PDF-"
