"""Tests for the employee-attendance exports feature.

Covers three pure layers without spinning up the app (matches the repo's
service-level test convention):
  - the export service (response models → ExportTable row matrix),
  - the route's pure range-resolution helper, and
  - the Excel/PDF renderers (produce well-formed bytes).
"""

from datetime import date, datetime

from app.features.employees.models import (
    EmployeeDay,
    EmployeesTodayResponse,
    EmployeesWeekResponse,
    EmployeeWeek,
    EmployeeWeekDay,
)
from app.features.exports.excel import render_xlsx
from app.features.exports.pdf import render_pdf
from app.features.exports.route import _filename, _period_label, _resolve_range
from app.features.exports.service import (
    build_daily_export,
    build_range_export,
)

_DAY = date(2026, 5, 12)


def _eday(
    code: str,
    name: str,
    *,
    pin: datetime | None = None,
    pout: datetime | None = None,
    worked: int | None = None,
    absent: bool = False,
    on_leave: bool = False,
    on_holiday: bool = False,
) -> EmployeeDay:
    return EmployeeDay(
        emp_code=code,
        name=name,
        punch_in=pin,
        punch_out=pout,
        worked_minutes=worked,
        absent=absent,
        on_leave=on_leave,
        on_holiday=on_holiday,
    )


# ---------- Daily export ----------


class TestDailyExport:
    def test_columns_and_row_shape(self):
        resp = EmployeesTodayResponse(
            date=_DAY.isoformat(),
            rows=[
                _eday(
                    "1001",
                    "Khaled",
                    pin=datetime(2026, 5, 12, 9, 5),
                    pout=datetime(2026, 5, 12, 17, 30),
                    worked=505,
                ),
            ],
        )
        table = build_daily_export(resp, period_label="Tuesday, 12-05-2026")
        assert table.columns == [
            "Emp code",
            "Name",
            "Punch in",
            "Punch out",
            "Worked time",
        ]
        assert table.rows == [["1001", "Khaled", "09:05", "17:30", "8h 25m"]]
        # No section banners in the flat daily layout.
        assert table.section_rows == set()

    def test_single_punch_shows_dash_and_no_duration(self):
        resp = EmployeesTodayResponse(
            date=_DAY.isoformat(),
            rows=[_eday("1002", "Layla", pin=datetime(2026, 5, 12, 8, 45))],
        )
        table = build_daily_export(resp, period_label="x")
        assert table.rows[0] == ["1002", "Layla", "08:45", "—", "—"]

    def test_status_words_for_excused_and_absent(self):
        resp = EmployeesTodayResponse(
            date=_DAY.isoformat(),
            rows=[
                _eday("1", "Absent One", absent=True),
                _eday("2", "Leave One", on_leave=True),
                _eday("3", "Holiday One", on_holiday=True),
                # Holiday wins over leave when both set.
                _eday("4", "Both", on_leave=True, on_holiday=True),
            ],
        )
        table = build_daily_export(resp, period_label="x")
        status_by_name = {r[1]: r[4] for r in table.rows}
        assert status_by_name["Absent One"] == "Absent"
        assert status_by_name["Leave One"] == "On leave"
        assert status_by_name["Holiday One"] == "Holiday"
        assert status_by_name["Both"] == "Holiday"

    def test_sorted_by_emp_code_descending_numeric(self):
        resp = EmployeesTodayResponse(
            date=_DAY.isoformat(),
            rows=[_eday("1001", "A"), _eday("1010", "B"), _eday("1002", "C")],
        )
        table = build_daily_export(resp, period_label="x")
        assert [r[0] for r in table.rows] == ["1010", "1002", "1001"]


# ---------- Range (weekly/monthly/custom) export ----------


class TestRangeExport:
    def test_section_banner_then_day_rows(self):
        resp = EmployeesWeekResponse(
            range_start="2026-05-10",
            range_end="2026-05-16",
            rows=[
                EmployeeWeek(
                    emp_code="1001",
                    name="Khaled",
                    days_worked=2,
                    expected_days=5,
                    total_worked_minutes=960,
                    expected_minutes=2400,
                    days=[
                        EmployeeWeekDay(
                            date="2026-05-10",
                            punch_in=datetime(2026, 5, 10, 9, 0),
                            punch_out=datetime(2026, 5, 10, 17, 0),
                            worked_minutes=480,
                        ),
                        EmployeeWeekDay(
                            date="2026-05-11",
                            punch_in=None,
                            punch_out=None,
                            worked_minutes=None,
                            absent=True,
                        ),
                    ],
                )
            ],
        )
        table = build_range_export(resp, period_label="10-05-2026 to 16-05-2026")
        # Row 0 is the employee banner; rows 1-2 are its days.
        assert table.section_rows == {0}
        banner = table.rows[0]
        assert banner[0] == "1001"
        assert banner[1] == "Khaled"
        assert banner[4] == "2 days · 16h 00m"
        # Day rows: date in col 0, blank name col, time + status.
        assert table.rows[1][0] == "Sun 10-05-2026"
        assert table.rows[1][1] == ""
        assert table.rows[1][4] == "8h 00m"
        assert table.rows[2][0] == "Mon 11-05-2026"
        assert table.rows[2][4] == "Absent"

    def test_multiple_employees_each_get_a_section(self):
        resp = EmployeesWeekResponse(
            range_start="2026-05-10",
            range_end="2026-05-16",
            rows=[
                EmployeeWeek(
                    emp_code="1001",
                    name="A",
                    days_worked=1,
                    expected_days=5,
                    total_worked_minutes=60,
                    expected_minutes=2400,
                    days=[
                        EmployeeWeekDay(
                            date="2026-05-10",
                            punch_in=datetime(2026, 5, 10, 9, 0),
                            punch_out=datetime(2026, 5, 10, 10, 0),
                            worked_minutes=60,
                        )
                    ],
                ),
                EmployeeWeek(
                    emp_code="1002",
                    name="B",
                    days_worked=1,
                    expected_days=5,
                    total_worked_minutes=120,
                    expected_minutes=2400,
                    days=[
                        EmployeeWeekDay(
                            date="2026-05-11",
                            punch_in=datetime(2026, 5, 11, 9, 0),
                            punch_out=datetime(2026, 5, 11, 11, 0),
                            worked_minutes=120,
                        )
                    ],
                ),
            ],
        )
        table = build_range_export(resp, period_label="x")
        # Two banners at indices 0 and 2 (each followed by one day row).
        assert table.section_rows == {0, 2}
        assert table.rows[0][0] == "1001"
        assert table.rows[2][0] == "1002"


# ---------- Range resolution (pure route helper) ----------


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


# ---------- Filename + period label ----------


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


def _sample_daily_table():
    resp = EmployeesTodayResponse(
        date=_DAY.isoformat(),
        rows=[
            _eday(
                "1001",
                "Khaled",
                pin=datetime(2026, 5, 12, 9, 5),
                pout=datetime(2026, 5, 12, 17, 30),
                worked=505,
            ),
            _eday("1002", "Layla", absent=True),
        ],
    )
    return build_daily_export(resp, period_label="Tuesday, 12-05-2026")


class TestRenderers:
    def test_xlsx_has_zip_magic_and_nonzero_size(self):
        data = render_xlsx(_sample_daily_table())
        # .xlsx is a zip container → starts with "PK".
        assert data[:2] == b"PK"
        assert len(data) > 1000

    def test_pdf_has_pdf_magic_and_nonzero_size(self):
        data = render_pdf(_sample_daily_table())
        assert data[:5] == b"%PDF-"
        assert len(data) > 500

    def test_renderers_handle_empty_table(self):
        empty = EmployeesTodayResponse(date=_DAY.isoformat(), rows=[])
        table = build_daily_export(empty, period_label="x")
        assert render_xlsx(table)[:2] == b"PK"
        assert render_pdf(table)[:5] == b"%PDF-"

    def test_renderers_handle_grouped_table(self):
        resp = EmployeesWeekResponse(
            range_start="2026-05-10",
            range_end="2026-05-16",
            rows=[
                EmployeeWeek(
                    emp_code="1001",
                    name="Khaled",
                    days_worked=1,
                    expected_days=5,
                    total_worked_minutes=480,
                    expected_minutes=2400,
                    days=[
                        EmployeeWeekDay(
                            date="2026-05-10",
                            punch_in=datetime(2026, 5, 10, 9, 0),
                            punch_out=datetime(2026, 5, 10, 17, 0),
                            worked_minutes=480,
                        )
                    ],
                )
            ],
        )
        table = build_range_export(resp, period_label="x")
        assert render_xlsx(table)[:2] == b"PK"
        assert render_pdf(table)[:5] == b"%PDF-"
