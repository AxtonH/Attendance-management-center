"""Render an `AttendanceReport` to a PDF (reportlab).

The only place that knows the PDF format. Layout mirrors the Excel renderer:
a summary page (headline stats + per-employee overview table) followed by
one page per employee (info block, stat block, day-by-day table). reportlab
is pure-Python, so this deploys on Railway/Docker without native libs.
No attendance logic here — just layout.
"""

from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as PdfImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

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

# Prezlab dark header band / shading — match the Excel renderer.
_HEADER_BG = colors.HexColor("#1F2430")
_HEADER_FG = colors.white
_GRID = colors.HexColor("#E5E7EB")
_MUTED = colors.HexColor("#6B7280")
_FAINT = colors.HexColor("#9CA3AF")

# Status text colors — same palette as the frontend pills / Excel renderer.
_STATUS_COLORS: dict[str, colors.Color] = {
    STATUS_LATE: colors.HexColor("#92400E"),
    STATUS_ABSENT: colors.HexColor("#991B1B"),
    STATUS_ON_LEAVE: colors.HexColor("#1E40AF"),
    STATUS_HOLIDAY: colors.HexColor("#065F46"),
    STATUS_WFH: colors.HexColor("#8C8C90"),
    STATUS_DAY_OFF: colors.HexColor("#8C8C90"),
    STATUS_UPCOMING: colors.HexColor("#C4C4C8"),
}
_MUTED_STATUSES = (STATUS_WFH, STATUS_DAY_OFF, STATUS_UPCOMING)

_STYLES = getSampleStyleSheet()
_TITLE = ParagraphStyle(
    "RptTitle", parent=_STYLES["Title"], fontSize=16, alignment=0, spaceAfter=2
)
_SUBTITLE = ParagraphStyle(
    "RptSubtitle", parent=_STYLES["Normal"], fontSize=9.5, textColor=_MUTED, spaceAfter=2
)
_H2 = ParagraphStyle(
    "RptH2",
    parent=_STYLES["Heading2"],
    fontSize=13,
    spaceBefore=0,
    spaceAfter=2,
)

# Portrait A4 content width is ~190mm (10mm margins).
_OVERVIEW_WIDTHS_MM = [42, 32, 17, 12, 14, 17, 20, 22]
_DAY_WIDTHS_MM = [24, 13, 22, 19, 19, 19, 15]


def render_pdf(report: AttendanceReport) -> bytes:
    """Build the PDF and return it as bytes."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        title=report.title,
    )

    elements: list = [
        Paragraph(report.title, _TITLE),
        Paragraph(report.period_label, _SUBTITLE),
        Paragraph(report.generated_label, _SUBTITLE),
        Spacer(1, 6 * mm),
        _stats_table(report),
        Spacer(1, 6 * mm),
    ]
    if report.arrival_histogram:
        # Same dashboard-style chart PNG the Excel summary embeds. Keep the
        # source aspect ratio (chart.WIDTH × chart.HEIGHT).
        png = chart.render_arrival_chart_png(report.arrival_histogram)
        img_w = 140 * mm
        img_h = img_w * chart.HEIGHT / chart.WIDTH
        elements.append(Paragraph("Arrival pattern", _H2))
        elements.append(Spacer(1, 2 * mm))
        elements.append(PdfImage(BytesIO(png), width=img_w, height=img_h, hAlign="LEFT"))
        elements.append(Spacer(1, 6 * mm))
    if report.overview_rows:
        elements.append(_overview_table(report))
    else:
        elements.append(Paragraph("No employees in this report.", _SUBTITLE))

    for section in report.sections:
        elements.append(PageBreak())
        elements.extend(_employee_page(section, report.period_label))

    doc.build(elements)
    return buffer.getvalue()


def _stats_table(report: AttendanceReport) -> Table:
    """Headline stats as a compact label/value/detail list."""
    data = [[s.label, s.value, s.detail] for s in report.stats]
    tbl = Table(data, colWidths=[34 * mm, 30 * mm, 100 * mm])
    tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
                ("TEXTCOLOR", (0, 0), (0, -1), _MUTED),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTSIZE", (1, 0), (1, -1), 11),
                ("TEXTCOLOR", (2, 0), (2, -1), _FAINT),
                ("FONTSIZE", (2, 0), (2, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, _GRID),
            ]
        )
    )
    return tbl


def _overview_table(report: AttendanceReport) -> Table:
    data = [report.overview_columns, *report.overview_rows]
    tbl = Table(
        data,
        colWidths=[w * mm for w in _OVERVIEW_WIDTHS_MM],
        repeatRows=1,
    )
    tbl.setStyle(TableStyle(_table_base_style()))
    return tbl


def _employee_page(section: EmployeeSection, period_label: str) -> list:
    dept = f" · {section.department}" if section.department else ""
    elements: list = [
        Paragraph(section.name, _H2),
        Paragraph(f"Emp code {section.emp_code}{dept}", _SUBTITLE),
        Paragraph(period_label, _SUBTITLE),
        Spacer(1, 4 * mm),
    ]

    # Stat block: two label/value pairs per row, mirroring the Excel sheet.
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
    rows = [pairs[i : i + 2] for i in range(0, len(pairs), 2)]
    data = []
    for pair in rows:
        left, right = pair[0], pair[1] if len(pair) > 1 else ("", "")
        data.append([left[0], left[1], right[0], right[1]])
    stat_tbl = Table(data, colWidths=[34 * mm, 26 * mm, 34 * mm, 26 * mm])
    stat_tbl.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (0, -1), _MUTED),
                ("TEXTCOLOR", (2, 0), (2, -1), _MUTED),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("FONTNAME", (3, 0), (3, -1), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    elements.append(stat_tbl)
    elements.append(Spacer(1, 5 * mm))
    elements.append(_day_table(section))
    return elements


def _day_table(section: EmployeeSection) -> Table:
    columns = ["Date", "Day", "Status", "Check-in", "Check-out", "Worked", "Late by"]
    data = [columns]
    style = _table_base_style()

    for i, line in enumerate(section.days, start=1):
        data.append(
            [
                line.date,
                line.weekday,
                line.status,
                line.check_in,
                line.check_out,
                line.worked,
                line.late_by,
            ]
        )
        color = _STATUS_COLORS.get(line.status)
        if color is not None:
            style.append(("TEXTCOLOR", (2, i), (2, i), color))
            if line.status not in _MUTED_STATUSES:
                style.append(("FONTNAME", (2, i), (2, i), "Helvetica-Bold"))
        if line.status in _MUTED_STATUSES:
            style.append(("TEXTCOLOR", (0, i), (-1, i), _FAINT))

    tbl = Table(data, colWidths=[w * mm for w in _DAY_WIDTHS_MM], repeatRows=1)
    tbl.setStyle(TableStyle(style))
    return tbl


def _table_base_style() -> list:
    """Shared header-band + grid treatment for data tables."""
    return [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
