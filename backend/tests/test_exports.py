"""Tests for the employee-attendance exports feature.

Covers three pure layers without spinning up the app (matches the repo's
service-level test convention):
  - the report builder (response models → AttendanceReport),
  - the route's pure helpers (range resolution, emp_codes parsing), and
  - the Excel/PDF renderers (produce well-formed bytes).
"""

from datetime import date, datetime, timedelta

from app.features.employees.models import (
    EmployeesWeekResponse,
    EmployeeWeek,
    EmployeeWeekDay,
)
from app.features.exports.excel import render_xlsx
from app.features.exports.pdf import render_pdf
from app.features.exports.report import (
    STATUS_ABSENT,
    STATUS_HOLIDAY,
    STATUS_LATE,
    STATUS_ON_LEAVE,
    STATUS_PRESENT,
    STATUS_UPCOMING,
    STATUS_WEEKEND,
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

    def test_gap_days_weekend_wfh_and_upcoming(self):
        # Employee has no rows at all: Sun is their weekend (their schedule
        # doesn't cover it), Mon has no schedule info (upcoming/no-data), and
        # Thu 2026-05-14 is scheduled but the org WFH weekday.
        days_in_period = [date(2026, 5, 10), date(2026, 5, 11), date(2026, 5, 14)]
        working = {
            date(2026, 5, 10): frozenset({"other"}),  # not scheduled → weekend
            date(2026, 5, 11): None,  # no schedule info
            date(2026, 5, 14): frozenset({"1"}),  # scheduled, WFH weekday
        }
        report = _build(
            [_week("1", "A", [])],
            days=days_in_period,
            working_emp_codes_by_day=working,
        )
        statuses = [line.status for line in report.sections[0].days]
        assert statuses == [STATUS_WEEKEND, STATUS_UPCOMING, STATUS_WFH]

    def test_weekend_follows_the_employees_own_schedule(self):
        # A Fri–Sat worker: their weekend falls on Sun/Mon, not Fri/Sat.
        # Fri 2026-05-15, Sat 16, Sun 17, Mon 18.
        days_in_period = [
            date(2026, 5, 15),
            date(2026, 5, 16),
            date(2026, 5, 17),
            date(2026, 5, 18),
        ]
        working = {
            date(2026, 5, 15): frozenset({"1"}),
            date(2026, 5, 16): frozenset({"1"}),
            date(2026, 5, 17): frozenset({"other"}),
            date(2026, 5, 18): frozenset({"other"}),
        }
        section = _build(
            [_week("1", "A", [])],
            days=days_in_period,
            working_emp_codes_by_day=working,
        ).sections[0]
        assert [line.status for line in section.days][2:] == [
            STATUS_WEEKEND,
            STATUS_WEEKEND,
        ]
        assert section.schedule_label == "Fri – Sat"


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

    def test_missing_hours_per_day_floors_at_zero(self):
        days = [
            _wday(  # 30m short of the 480m full day
                "2026-05-10",
                pin=datetime(2026, 5, 10, 9, 0),
                pout=datetime(2026, 5, 10, 16, 30),
                worked=450,
            ),
            _wday(  # an hour over — "nothing missing", never negative
                "2026-05-11",
                pin=datetime(2026, 5, 11, 9, 0),
                pout=datetime(2026, 5, 11, 18, 0),
                worked=540,
            ),
            _wday("2026-05-12", absent=True),
        ]
        section = _build([_week("1", "A", days)], days=_DAYS[:3]).sections[0]
        assert [line.missing_hours for line in section.days] == [
            "0h 30m",
            "0h 00m",
            "—",  # nothing worked, so no shortfall to report
        ]

    def test_profile_and_tile_fields(self):
        days = [
            _wday(
                "2026-05-10",
                pin=datetime(2026, 5, 10, 9, 0),
                pout=datetime(2026, 5, 10, 17, 30),
                worked=510,
            ),
            _wday("2026-05-11", absent=True),
        ]
        section = _build(
            [_week("1001", "A", days)],
            days=_DAYS[:2],
            pod_by_emp_code={"1001": "Motion"},
        ).sections[0]
        assert section.pod == "Motion"
        assert section.shift_start == "09:00"
        assert section.shift_end == "17:00"  # 09:00 + full_day_minutes
        assert section.full_day == "8h 00m"
        # 2 expected days (1 attended + 1 absent) × the 8h target.
        assert section.expected_worked == "16h 00m"
        assert section.avg_departure == "17:30"

    def test_pod_defaults_to_blank_without_odoo_data(self):
        section = _build([_week("1", "A", [])]).sections[0]
        assert section.pod == ""

    def test_schedule_label_shapes(self):
        def label_for(weekdays: set[int]) -> str:
            # Two full weeks so every weekday appears in the period.
            period = [date(2026, 5, 10) + timedelta(days=i) for i in range(14)]
            working = {
                d: frozenset({"1"}) if d.weekday() in weekdays else frozenset()
                for d in period
            }
            return _build(
                [_week("1", "A", [])],
                days=period,
                working_emp_codes_by_day=working,
            ).sections[0].schedule_label

        assert label_for({6, 0, 1, 2, 3}) == "Sun – Thu"  # the org default
        assert label_for({4, 5}) == "Fri – Sat"
        assert label_for({0, 2, 4}) == "Mon, Wed, Fri"  # non-contiguous
        assert label_for({1}) == "Tue"  # single day, no range
        assert label_for(set(range(7))) == "Every day"

    def test_schedule_label_is_dash_without_schedule_data(self):
        # Phase-1 fallback: no schedule info for any day in the period.
        assert _build([_week("1", "A", [])]).sections[0].schedule_label == "—"

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
        # Bucket windows are always present; with no samples every count
        # is zero, so the pattern charts render flat rather than crashing.
        assert all(b.count == 0 for b in report.arrival_buckets)
        assert all(b.count == 0 for b in report.departure_buckets)

    def test_fixed_buckets_track_the_configured_shift(self):
        # Arrivals relative to the 09:00 start; departures relative to the
        # derived 17:00 end (start + full_day_minutes). Bounds are half-open,
        # so 09:15 lands in 09:15–09:30, not 09:00–09:15.
        rows = [
            _week(
                "1",
                "A",
                [
                    _wday(
                        "2026-05-10",
                        pin=datetime(2026, 5, 10, 8, 40),
                        pout=datetime(2026, 5, 10, 16, 15),
                    ),
                    _wday(
                        "2026-05-11",
                        pin=datetime(2026, 5, 11, 9, 15),
                        pout=datetime(2026, 5, 11, 17, 0),
                    ),
                    _wday(
                        "2026-05-12",
                        pin=datetime(2026, 5, 12, 11, 30),
                        pout=datetime(2026, 5, 12, 19, 0),
                    ),
                ],
            )
        ]
        report = _build(rows)
        arrivals = {b.label: b.count for b in report.arrival_buckets}
        assert arrivals["08:30–09:00"] == 1
        assert arrivals["09:00–09:15"] == 0
        assert arrivals["09:15–09:30"] == 1
        assert arrivals["10:30+"] == 1
        departures = {b.label: b.count for b in report.departure_buckets}
        assert departures["Before 16:30"] == 1
        assert departures["17:00–17:15"] == 1  # 17:00 is on-time, not early
        assert departures["17:45+"] == 1

    def test_key_metrics_are_the_four_hero_tiles(self):
        days = [
            _wday(
                "2026-05-10",
                pin=datetime(2026, 5, 10, 9, 0),
                pout=datetime(2026, 5, 10, 17, 30),  # on-time departure
                worked=510,
            ),
            _wday(
                "2026-05-11",
                pin=datetime(2026, 5, 11, 10, 0),  # late
                pout=datetime(2026, 5, 11, 16, 0),  # early departure
                worked=360,
            ),
            _wday("2026-05-12", absent=True),
        ]
        report = _build([_week("1", "A", days)], days=_DAYS[:3])
        labels = [m.label for m in report.key_metrics]
        assert labels == [
            "Attendance rate",
            "Punctuality rate",
            "On-time departures",
            "Total employees",
        ]
        values = {m.label: m.value for m in report.key_metrics}
        assert values["Attendance rate"] == "67%"  # 2 attended of 3 expected
        assert values["Punctuality rate"] == "50%"  # 1 on-time of 2 present
        assert values["On-time departures"] == "50%"  # 1 of 2 recorded
        assert values["Total employees"] == "1"

    def test_missing_minutes_floors_per_day(self):
        # 510 worked (over the 480 full day) then 360 (120 short). Overtime
        # on one day must not offset the shortfall on another.
        days = [
            _wday(
                "2026-05-10",
                pin=datetime(2026, 5, 10, 9, 0),
                pout=datetime(2026, 5, 10, 17, 30),
                worked=510,
            ),
            _wday(
                "2026-05-11",
                pin=datetime(2026, 5, 11, 9, 0),
                pout=datetime(2026, 5, 11, 15, 0),
                worked=360,
            ),
        ]
        section = _build([_week("1", "A", days)], days=_DAYS[:2]).sections[0]
        assert section.missing_minutes == 120

    def test_rankings_are_top_three_and_skip_zeroes(self):
        rows = [
            _week("1", "Alia", [_wday("2026-05-10", absent=True)]),
            _week(
                "2",
                "Basel",
                [_wday("2026-05-10", absent=True), _wday("2026-05-11", absent=True)],
            ),
            # No absences at all → must not appear on the absentee podium.
            _week("3", "Cara", [_wday("2026-05-10", pin=datetime(2026, 5, 10, 9, 0))]),
        ]
        report = _build(rows)
        by_title = {r.title: r for r in report.rankings}
        absentees = by_title["Top Absentees"]
        assert [(e.name, e.value) for e in absentees.entries] == [
            ("Basel", "2"),
            ("Alia", "1"),
        ]
        # All four podiums always exist, even when a measure has no entries.
        assert len(report.rankings) == 4
        assert set(by_title) == {
            "Top Absentees",
            "Most Late Arrivals",
            "Most Hours Missing",
            "Missing Sign-in/out",
        }
        # Nobody arrived late, so that podium is empty (the renderer pads it).
        assert by_title["Most Late Arrivals"].entries == []

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
            # A name Excel can't take verbatim as a sheet title; also long
            # enough to exercise the PDF's wrapping name cells.
            _week("1002", "S/mith [Very Long Name Beyond The Sheet Cap]", days),
            # Duplicate name → dedupe suffix path.
            _week("1003", "Khaled", []),
        ],
        # "&" is markup-significant in reportlab Paragraphs — a real
        # department name (People & Culture) must render literally.
        department_by_emp_code={"1001": "Animation", "1002": "People & Culture"},
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

    def test_summary_follows_the_brand_template_grid(self):
        from io import BytesIO

        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(render_xlsx(_sample_report())))
        ws = wb["Summary"]
        # Content sits on the B:I grid with a narrow column A gutter, and
        # the sheet reads as a page rather than a spreadsheet.
        assert ws.sheet_view.showGridLines is False
        assert ws.column_dimensions["A"].width < 3
        # Section anchors land on the template's rows.
        assert ws["B2"].value == "prezlab:"
        assert ws["B3"].value == "Attendance Report"
        assert ws["B4"].value == "Team Summary"
        assert ws["B8"].value == "KEY METRICS"
        assert ws["B15"].value == "ARRIVAL & DEPARTURE PATTERN"
        assert ws["B42"].value == "EMPLOYEES"
        # Rankings sit below the employee table, so their row depends on
        # headcount — find the section rather than pinning it to a row.
        column_b = [ws.cell(row=r, column=2).value for r in range(1, ws.max_row + 1)]
        assert "TOP RANKINGS" in column_b
        assert column_b.index("TOP RANKINGS") > column_b.index("EMPLOYEES")
        # The four hero tiles, then both bucket tables side by side.
        assert ws["B10"].value == "Attendance rate"
        assert ws["H10"].value == "Total employees"
        assert ws["B17"].value == "Arrival"
        assert ws["F17"].value == "Departure"
        # Native bar charts over each bucket table (no PNG in the summary).
        assert len(ws._charts) == 2
        # Both axes must be drawn. openpyxl leaves `delete` unset by default,
        # which Excel reads as "hide" — bars with no time labels or counts.
        for bar in ws._charts:
            for axis in (bar.x_axis, bar.y_axis):
                assert axis.delete is False
                assert axis.tickLblPos == "nextTo"

    def test_employee_sheet_follows_the_brand_template_grid(self):
        from io import BytesIO

        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(render_xlsx(_sample_report())))
        ws = wb["Khaled"]
        assert ws.sheet_view.showGridLines is False
        assert ws.column_dimensions["A"].width < 3
        # Section anchors land on the template's rows.
        assert ws["B2"].value == "prezlab:"
        assert ws["B8"].value == "PROFILE"
        assert ws["B9"].value == "Employee code"
        assert ws["F9"].value == "Schedule"
        assert ws["B11"].value == "Pool / Team"
        assert ws["B13"].value == "SUMMARY"
        assert ws["B15"].value == "Days attended"
        assert ws["F15"].value == "Attendance"
        assert ws["B28"].value == "DAILY LOG"
        assert ws["H29"].value == "Missing hours"
        # The back-link returns to the summary sheet.
        assert ws["H2"].value == "← Summary"
        assert ws["H2"].hyperlink.location == "'Summary'!A1"

    def test_pattern_charts_align_with_their_bucket_tables(self):
        # Charts are anchored cell-to-cell across exactly their own bucket
        # table's columns (arrival B:D, departure F:I), so Excel pins both
        # edges to the same column boundaries the tables end on — on any
        # screen, DPI, or zoom. A fixed width (EMU extent) can't guarantee
        # that: on-screen column pixel widths vary with the viewer's font
        # metrics and DPI scaling, so a hardcoded extent that looks flush on
        # one machine overhangs or falls short on another.
        from io import BytesIO

        from openpyxl import load_workbook
        from openpyxl.drawing.spreadsheet_drawing import TwoCellAnchor

        wb = load_workbook(BytesIO(render_xlsx(_sample_report())))
        ws = wb["Summary"]
        assert len(ws._charts) == 2

        spans = {}
        for chart in ws._charts:
            anchor = chart.anchor
            assert isinstance(anchor, TwoCellAnchor), (
                "chart must be cell-anchored, not fixed-extent"
            )
            # Zero offsets: edges sit exactly on the column boundaries.
            assert anchor._from.colOff == 0
            assert anchor.to.colOff == 0
            spans[anchor._from.col] = anchor.to.col
        # 0-based; `to.col` is the boundary after the span's last column.
        # B:D → from 1 to 4 (edge of D|E); F:I → from 5 to 9 (edge of I|J).
        assert spans == {1: 4, 5: 9}

    def test_pattern_blocks_are_equal_width(self):
        # The arrival block (B:D) and departure block (F:I) must render at
        # the same width so the side-by-side tables and their cell-anchored
        # charts read as a matched pair. Rendered width is a viewer-side
        # property (per-column padding rounds with the viewer's DPI), so the
        # exact value is calibrated by measuring both spans in Excel itself,
        # not computable in a test. This guards that calibration: the unit
        # sums stay within one column-padding of each other — the template's
        # layout was 4 units (~25px) apart, which is what showed on screen.
        from app.features.exports.excel import _SUM_WIDTHS

        arrival = sum(_SUM_WIDTHS[c - 1] for c in (2, 3, 4))
        departure = sum(_SUM_WIDTHS[c - 1] for c in (6, 7, 8, 9))
        assert abs(arrival - departure) < 1.5

    def test_tables_and_tiles_are_ruled(self):
        # Borders carry the reading structure: without them the tiles bleed
        # together and the log loses its columns.
        from io import BytesIO

        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(render_xlsx(_sample_report())))

        summary = wb["Summary"]
        # Bucket table (B17 header) boxed on its top-left corner.
        assert summary["B17"].border.left.style == "thin"
        assert summary["B17"].border.top.style == "thin"
        # Employees table header ruled, with a column separator.
        assert summary["B43"].border.top.style == "thin"
        assert summary["B43"].border.right.style == "thin"

        ws = wb["Khaled"]
        # Each SUMMARY tile is boxed: B15 is the first tile's top-left.
        assert ws["B15"].border.left.style == "thin"
        assert ws["B15"].border.top.style == "thin"
        # C17 closes that tile on its bottom-right.
        assert ws["C17"].border.right.style == "thin"
        assert ws["C17"].border.bottom.style == "thin"
        # Daily-log header ruled top, with column separators.
        assert ws["B29"].border.top.style == "thin"
        assert ws["B29"].border.right.style == "thin"

    def test_employee_status_key_covers_every_pill_used(self):
        from io import BytesIO

        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(render_xlsx(_sample_report())))
        ws = wb["Khaled"]
        # Find the legend row, then collect its swatches.
        column_b = [ws.cell(row=r, column=2).value for r in range(1, ws.max_row + 1)]
        key_row = column_b.index("STATUS KEY") + 2
        legend = {
            ws.cell(row=key_row, column=c).value
            for c in range(2, 10)
            if ws.cell(row=key_row, column=c).value
        }
        # Every status appearing in the daily log must be in the key.
        log_start = column_b.index("DAILY LOG") + 3  # header row then data
        used = {
            ws.cell(row=r, column=4).value
            for r in range(log_start, log_start + 4)
            if ws.cell(row=r, column=4).value
        }
        assert used <= legend, f"{used - legend} missing from the status key"

    def test_pdf_has_pdf_magic_and_nonzero_size(self):
        data = render_pdf(_sample_report())
        assert data[:5] == b"%PDF-"
        assert len(data) > 500

    def test_renderers_handle_empty_report(self):
        report = _build([])
        assert render_xlsx(report)[:2] == b"PK"
        assert render_pdf(report)[:5] == b"%PDF-"
