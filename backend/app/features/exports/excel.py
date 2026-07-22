"""Render an `AttendanceReport` to an .xlsx workbook (openpyxl).

The only place that knows the Excel format. The visual system follows the
P&C reference timesheet workbook — dark title band, section bands, light
label cells for info/stat grids, a strong colored table header, alternating
row fills, thin borders throughout — translated into Prezlab's indigo
palette. Structure: a "Summary" sheet (info grid, headline stats, native
arrival-pattern bar chart, per-employee overview with hyperlinks) followed
by one sheet per employee (info grid, stat grid, daily log).

No attendance logic here — just layout.
"""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.drawing.image import Image as XlsxImage
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink
from openpyxl.worksheet.worksheet import Worksheet

from app.features.exports import chart

from app.features.exports.report import (
    STATUS_ABSENT,
    STATUS_DAY_OFF,
    STATUS_HOLIDAY,
    STATUS_LATE,
    STATUS_ON_LEAVE,
    STATUS_UPCOMING,
    STATUS_WFH,
    AttendanceReport,
    EmployeeSection,
)

# ---------- Visual system (reference workbook, Prezlab palette) ----------

_INK = "1F2430"  # app bg-dark — title + section bands
_ACCENT = "4F46E5"  # app accent — table headers, chart bars
_ACCENT_INK = "312E81"  # dark indigo — label-cell text
_LABEL_BG = "E8EAF9"  # light indigo — label cells (reference's D9E1F2)
_ALT_BG = "F5F6FE"  # alternating data rows (reference's F2F7FC)
_GRID = "D5D8EA"  # thin border color
_MUTED = "8C8C90"

_BAND_FILL = PatternFill("solid", fgColor=_INK)
_BAND_FONT = Font(bold=True, size=12, color="FFFFFF")
_TITLE_FONT = Font(bold=True, size=14, color="FFFFFF")
_TABLE_HEADER_FILL = PatternFill("solid", fgColor=_ACCENT)
_TABLE_HEADER_FONT = Font(bold=True, size=10, color="FFFFFF")
_LABEL_FILL = PatternFill("solid", fgColor=_LABEL_BG)
_LABEL_FONT = Font(bold=True, size=10, color=_ACCENT_INK)
_VALUE_FONT = Font(size=10)
_VALUE_BOLD_FONT = Font(bold=True, size=11)
_DETAIL_FONT = Font(size=9, color=_MUTED)
_BODY_FONT = Font(size=10)
_MUTED_FONT = Font(size=10, color="9CA3AF")
_ALT_FILL = PatternFill("solid", fgColor=_ALT_BG)
_LINK_FONT = Font(size=10, color=_ACCENT, underline="single")

_THIN = Side(style="thin", color=_GRID)
_BOX = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

_CENTER = Alignment(horizontal="center", vertical="center")
_LEFT = Alignment(horizontal="left", vertical="center")

_BAND_HEIGHT = 24
_TITLE_HEIGHT = 30
_ROW_HEIGHT = 18

# Status pill colors — same palette as the frontend pills so the file reads
# like the screen. (fill, font-color); None fill = plain colored text.
_STATUS_STYLES: dict[str, tuple[str | None, str]] = {
    STATUS_LATE: ("FEF3C7", "92400E"),
    STATUS_ABSENT: ("FEE2E2", "991B1B"),
    STATUS_ON_LEAVE: ("DBEAFE", "1E40AF"),
    STATUS_HOLIDAY: ("D1FAE5", "065F46"),
    STATUS_WFH: (None, _MUTED),
    STATUS_DAY_OFF: (None, _MUTED),
    STATUS_UPCOMING: (None, "C4C4C8"),
}
_MUTED_STATUSES = (STATUS_WFH, STATUS_DAY_OFF, STATUS_UPCOMING)

_SUMMARY_SHEET = "Summary"
# Excel sheet-name hard limits: 31 chars, none of []:*?/\ .
_SHEET_NAME_BAD = str.maketrans("", "", "[]:*?/\\")
_SHEET_NAME_MAX = 28  # leave room for a " (n)" dedupe suffix


def render_xlsx(report: AttendanceReport) -> bytes:
    """Build the workbook and return it as bytes."""
    wb = Workbook()
    summary = wb.active
    summary.title = _SUMMARY_SHEET

    sheet_names = _sheet_names(report.sections)
    _render_summary(summary, report, sheet_names)
    for section, sheet_name in zip(report.sections, sheet_names, strict=True):
        ws = wb.create_sheet(title=sheet_name)
        _render_employee_sheet(ws, section, report.period_label)

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _sheet_names(sections: list[EmployeeSection]) -> list[str]:
    """Legal, unique sheet name per employee (Excel: ≤31 chars, no []:*?/\\)."""
    seen: dict[str, int] = {}
    names: list[str] = []
    for s in sections:
        base = (s.name.translate(_SHEET_NAME_BAD).strip() or s.emp_code)[
            :_SHEET_NAME_MAX
        ].strip()
        count = seen.get(base.lower(), 0)
        seen[base.lower()] = count + 1
        names.append(base if count == 0 else f"{base} ({count + 1})")
    return names


# ---------- Shared building blocks ----------


def _band(ws: Worksheet, row: int, n_cols: int, text: str, *, title: bool = False) -> None:
    """A full-width dark band — the sheet title or a section header."""
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
    cell = ws.cell(row=row, column=1, value=text)
    cell.fill = _BAND_FILL
    cell.font = _TITLE_FONT if title else _BAND_FONT
    cell.alignment = _LEFT
    # Fill the merged range so the band has no white seams.
    for col in range(2, n_cols + 1):
        ws.cell(row=row, column=col).fill = _BAND_FILL
    ws.row_dimensions[row].height = _TITLE_HEIGHT if title else _BAND_HEIGHT


def _label_value(
    ws: Worksheet,
    row: int,
    *,
    label: str,
    value: str,
    label_span: tuple[int, int],
    value_span: tuple[int, int],
    bold_value: bool = False,
) -> None:
    """One reference-style info pair: filled label cell + bordered value cell."""
    lc0, lc1 = label_span
    vc0, vc1 = value_span
    if lc1 > lc0:
        ws.merge_cells(start_row=row, start_column=lc0, end_row=row, end_column=lc1)
    if vc1 > vc0:
        ws.merge_cells(start_row=row, start_column=vc0, end_row=row, end_column=vc1)
    for col in range(lc0, lc1 + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = _LABEL_FILL
        cell.border = _BOX
    for col in range(vc0, vc1 + 1):
        ws.cell(row=row, column=col).border = _BOX
    label_cell = ws.cell(row=row, column=lc0, value=label)
    label_cell.font = _LABEL_FONT
    label_cell.alignment = _LEFT
    value_cell = ws.cell(row=row, column=vc0, value=value)
    value_cell.font = _VALUE_BOLD_FONT if bold_value else _VALUE_FONT
    value_cell.alignment = _LEFT
    ws.row_dimensions[row].height = _ROW_HEIGHT


def _table_header(ws: Worksheet, row: int, columns: list[str]) -> None:
    for col, name in enumerate(columns, start=1):
        cell = ws.cell(row=row, column=col, value=name)
        cell.fill = _TABLE_HEADER_FILL
        cell.font = _TABLE_HEADER_FONT
        cell.alignment = _CENTER
        cell.border = _BOX
    ws.row_dimensions[row].height = _ROW_HEIGHT + 2


def _set_widths(ws: Worksheet, widths: list[int]) -> None:
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width


# ---------- Summary sheet ----------


def _render_summary(
    ws: Worksheet, report: AttendanceReport, sheet_names: list[str]
) -> None:
    n_cols = len(report.overview_columns)
    _set_widths(ws, [26, 18, 10, 8, 8, 10, 12, 14][:n_cols])

    _band(ws, 1, n_cols, report.title, title=True)
    _label_value(
        ws, 2, label="Period", value=report.period_label,
        label_span=(1, 1), value_span=(2, 3),
    )
    _label_value(
        ws, 2, label="Generated",
        value=report.generated_label.removeprefix("Generated "),
        label_span=(4, 4), value_span=(5, 5),
    )
    _label_value(
        ws, 2, label="Employees", value=str(len(report.sections)),
        label_span=(6, 6), value_span=(7, 8),
    )

    # Headline stats.
    row = 4
    _band(ws, row, n_cols, "Summary")
    for stat in report.stats:
        row += 1
        _label_value(
            ws, row, label=stat.label, value=stat.value,
            label_span=(1, 2), value_span=(3, 3), bold_value=True,
        )
        if stat.detail:
            ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=n_cols)
            for col in range(4, n_cols + 1):
                ws.cell(row=row, column=col).border = _BOX
            detail_cell = ws.cell(row=row, column=4, value=stat.detail)
            detail_cell.font = _DETAIL_FONT
            detail_cell.alignment = _LEFT
        else:
            for col in range(4, n_cols + 1):
                ws.cell(row=row, column=col).border = _BOX

    # Arrival pattern: bucket table in A:B + the dashboard-style chart PNG
    # floating next to it.
    if report.arrival_histogram:
        row += 2
        _band(ws, row, n_cols, "Arrival pattern")
        row += 1
        chart_top = row
        _table_header(ws, row, ["Time", "Arrivals"])
        for bin_ in report.arrival_histogram:
            row += 1
            time_cell = ws.cell(row=row, column=1, value=bin_.label)
            count_cell = ws.cell(row=row, column=2, value=bin_.count)
            for cell in (time_cell, count_cell):
                cell.font = _BODY_FONT
                cell.border = _BOX
                cell.alignment = _CENTER
        image = XlsxImage(BytesIO(chart.render_arrival_chart_png(report.arrival_histogram)))
        image.width = chart.WIDTH
        image.height = chart.HEIGHT
        ws.add_image(image, f"D{chart_top}")
        # The image floats ~200px (~9 rows) tall over columns D+; make sure
        # the next section clears both the bucket table and the image.
        row = max(row, chart_top + 10)

    # Per-employee overview.
    row += 2
    _band(ws, row, n_cols, "Employees")
    row += 1
    header_row = row
    _table_header(ws, row, report.overview_columns)
    for i, (values, sheet_name) in enumerate(
        zip(report.overview_rows, sheet_names, strict=True)
    ):
        row += 1
        fill = _ALT_FILL if i % 2 == 1 else None
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = _BODY_FONT
            cell.border = _BOX
            cell.alignment = _LEFT if col <= 2 else _CENTER
            if fill:
                cell.fill = fill
        name_cell = ws.cell(row=row, column=1)
        name_cell.hyperlink = Hyperlink(
            ref=name_cell.coordinate, location=f"'{sheet_name}'!A1"
        )
        name_cell.font = _LINK_FONT
    if report.overview_rows:
        last_col = get_column_letter(n_cols)
        ws.auto_filter.ref = f"A{header_row}:{last_col}{row}"


# ---------- Per-employee sheets ----------

_DAY_COLUMNS = ["Date", "Day", "Status", "Check-in", "Check-out", "Worked", "Late by"]


def _render_employee_sheet(
    ws: Worksheet, section: EmployeeSection, period_label: str
) -> None:
    n_cols = len(_DAY_COLUMNS)
    _set_widths(ws, [13, 8, 12, 11, 11, 11, 10])

    _band(ws, 1, n_cols, section.name, title=True)
    _label_value(
        ws, 2, label="Emp code", value=section.emp_code,
        label_span=(1, 2), value_span=(3, 4),
    )
    _label_value(
        ws, 2, label="Period", value=period_label,
        label_span=(5, 5), value_span=(6, 7),
    )
    _label_value(
        ws, 3, label="Department", value=section.department or "—",
        label_span=(1, 2), value_span=(3, 4),
    )
    back = ws.cell(row=3, column=6, value="← Summary")
    back.hyperlink = Hyperlink(ref=back.coordinate, location=f"'{_SUMMARY_SHEET}'!A1")
    back.font = _LINK_FONT

    # Stat grid: two label/value pairs per row, reference info-block style.
    row = 5
    _band(ws, row, n_cols, "Summary")
    pairs = [
        ("Days expected", str(section.days_expected)),
        ("Avg arrival", section.avg_arrival),
        ("Attended", str(section.days_attended)),
        ("Total worked", section.total_worked),
        ("Late arrivals", str(section.days_late)),
        ("Avg worked / day", section.avg_worked),
        ("Absent", str(section.days_absent)),
        ("Missing sign-outs", str(section.missing_signouts)),
        ("On leave", str(section.days_on_leave)),
        ("Attendance", section.attendance_pct),
        ("Holidays", str(section.days_holiday)),
    ]
    for i in range(0, len(pairs), 2):
        row += 1
        left = pairs[i]
        _label_value(
            ws, row, label=left[0], value=left[1],
            label_span=(1, 2), value_span=(3, 3), bold_value=True,
        )
        if i + 1 < len(pairs):
            right = pairs[i + 1]
            _label_value(
                ws, row, label=right[0], value=right[1],
                label_span=(4, 5), value_span=(6, 7), bold_value=True,
            )
        else:
            for col in range(4, n_cols + 1):
                ws.cell(row=row, column=col).border = _BOX

    row += 2
    _band(ws, row, n_cols, "Daily log")
    row += 1
    _table_header(ws, row, _DAY_COLUMNS)

    for i, line in enumerate(section.days):
        row += 1
        values = [
            line.date,
            line.weekday,
            line.status,
            line.check_in,
            line.check_out,
            line.worked,
            line.late_by,
        ]
        muted = line.status in _MUTED_STATUSES
        alt = _ALT_FILL if i % 2 == 1 else None
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            cell.font = _MUTED_FONT if muted else _BODY_FONT
            cell.border = _BOX
            cell.alignment = _LEFT if col == 1 else _CENTER
            if alt:
                cell.fill = alt
        style = _STATUS_STYLES.get(line.status)
        if style:
            fill, color = style
            status_cell = ws.cell(row=row, column=3)
            if fill:
                status_cell.fill = PatternFill("solid", fgColor=fill)
            status_cell.font = Font(size=10, color=color, bold=fill is not None)
