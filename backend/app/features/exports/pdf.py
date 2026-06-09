"""Render an `ExportTable` to a PDF (reportlab).

The only place that knows the PDF format. Takes the renderer-agnostic
`ExportTable` from `exports.service` and returns the file as raw bytes, ready
to stream as a download. reportlab is pure-Python, so this deploys on
Railway/Docker without native libs. No attendance logic here — just layout.
"""

from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.features.exports.service import ExportTable

# Prezlab dark header band / section shading — match the Excel renderer.
_HEADER_BG = colors.HexColor("#1F2430")
_HEADER_FG = colors.white
_SECTION_BG = colors.HexColor("#EEF1F5")
_GRID = colors.HexColor("#E5E7EB")
_ROW_ALT = colors.HexColor("#FAFAFA")

# Column widths in mm across a landscape A4 content area (~277mm usable).
# code/day, name, in, out, worked/status.
_COL_WIDTHS_MM = [55, 80, 35, 35, 55]


def render_pdf(table: ExportTable) -> bytes:
    """Build the PDF and return it as bytes."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        title=table.title,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ExportTitle",
        parent=styles["Title"],
        fontSize=16,
        alignment=0,  # left
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "ExportSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#6B7280"),
        spaceAfter=10,
    )

    elements: list = [
        Paragraph(table.title, title_style),
        Paragraph(table.subtitle, subtitle_style),
        Spacer(1, 4),
    ]

    if table.rows:
        elements.append(_build_table(table))
    else:
        elements.append(Paragraph("No data for this period.", subtitle_style))

    doc.build(elements)
    return buffer.getvalue()


def _build_table(table: ExportTable) -> Table:
    data = [table.columns, *table.rows]
    col_widths = [w * mm for w in _COL_WIDTHS_MM[: len(table.columns)]]

    style_commands: list = [
        # Header row.
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        # Repeat the header row at the top of every page.
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, _GRID),
    ]

    # Section banners (per-employee headers in grouped mode). `section_rows`
    # holds indices into `table.rows`; +1 shifts past the header row.
    for row_idx in table.section_rows:
        data_row = row_idx + 1
        style_commands.append(
            ("BACKGROUND", (0, data_row), (-1, data_row), _SECTION_BG)
        )
        style_commands.append(
            ("FONTNAME", (0, data_row), (-1, data_row), "Helvetica-Bold")
        )

    # Zebra striping for non-section data rows improves scan-ability on
    # the flat daily layout. Skip when sections exist (banners already
    # break the table up visually).
    if not table.section_rows:
        for i in range(1, len(data)):
            if i % 2 == 0:
                style_commands.append(
                    ("BACKGROUND", (0, i), (-1, i), _ROW_ALT)
                )

    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(TableStyle(style_commands))
    return tbl
