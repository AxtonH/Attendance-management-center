"""Draw the arrival-pattern chart as a PNG (Pillow).

Visually mirrors the dashboard's ArrivalHistogram (recharts): a smooth
monotone area curve in the app's indigo accent, gradient-faded to the
baseline, small gray time labels along the bottom, no axes or gridlines.
Both export renderers embed the PNG, so the file matches the screen.

Drawn at 3× and downscaled for antialiasing (Pillow's polygon fill isn't
antialiased). Pure function of the bins — no I/O beyond the returned bytes.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFont

from app.features.exports.report import HistogramBin

_ACCENT = (79, 70, 229)  # #4F46E5 — app accent
_LABEL = (140, 140, 144)  # #8C8C90 — app text-tertiary
_AREA_ALPHA = 0.35  # gradient opacity at the top, fading to 0 (dashboard)

# Logical (embedded) size in px; drawn at _SCALE× then downscaled.
WIDTH = 560
HEIGHT = 200
_SCALE = 3


def render_arrival_chart_png(bins: list[HistogramBin]) -> bytes:
    """The arrival histogram as PNG bytes. `bins` must be non-empty."""
    scale = _SCALE
    w, h = WIDTH * scale, HEIGHT * scale
    pad_top = 12 * scale
    pad_side = 14 * scale
    label_band = 26 * scale
    plot_w = w - 2 * pad_side
    plot_h = h - pad_top - label_band
    baseline = pad_top + plot_h

    img = Image.new("RGB", (w, h), "white")

    n = len(bins)
    max_count = max(b.count for b in bins) or 1
    xs = [
        pad_side + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)
        for i in range(n)
    ]
    ys = [pad_top + plot_h * (1 - b.count / max_count) for b in bins]
    curve = _monotone_curve(xs, ys)

    # Area fill: an accent overlay whose alpha is the *minimum* of a vertical
    # fade (strong at the top of the plot, zero at the baseline) and the
    # area-under-curve mask — exactly recharts' linearGradient fill.
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(
        [*curve, (xs[-1], baseline), (xs[0], baseline)], fill=255
    )
    fade = Image.new("L", (w, h), 0)
    fade_draw = ImageDraw.Draw(fade)
    top_alpha = int(255 * _AREA_ALPHA)
    for y in range(pad_top, baseline):
        t = (y - pad_top) / plot_h
        fade_draw.line([(0, y), (w, y)], fill=int(top_alpha * (1 - t)))
    alpha = ImageChops.darker(mask, fade)
    img.paste(Image.new("RGB", (w, h), _ACCENT), (0, 0), alpha)

    # The curve stroke on top of the fill.
    draw = ImageDraw.Draw(img)
    draw.line(curve, fill=_ACCENT, width=2 * scale, joint="curve")

    _draw_labels(draw, bins, xs, baseline, scale)

    img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _draw_labels(
    draw: ImageDraw.ImageDraw,
    bins: list[HistogramBin],
    xs: list[float],
    baseline: float,
    scale: int,
) -> None:
    """Time labels under the plot — first, last, and evenly spaced between
    (recharts' interval="preserveStartEnd" behavior)."""
    font = _font(10 * scale)
    n = len(bins)
    step = max(1, -(-n // 8))  # ceil — at most ~8 labels
    indices = {0, n - 1, *range(0, n, step)}
    y = baseline + 8 * scale
    for i in sorted(indices):
        label = bins[i].label
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        draw.text((xs[i] - text_w / 2, y), label, font=font, fill=_LABEL)


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """A small sans font: system TTFs when available (Windows dev, most
    Linux images), Pillow's bundled default otherwise."""
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _monotone_curve(
    xs: list[float], ys: list[float], samples_per_segment: int = 24
) -> list[tuple[float, float]]:
    """Sample a monotone cubic (Fritsch–Carlson) interpolation of the points.

    Same family of curve as recharts' type="monotone": smooth, but never
    overshooting past the data values, so a zero bucket stays at zero.
    """
    n = len(xs)
    if n == 1:
        return [(xs[0], ys[0]), (xs[0] + 1, ys[0])]

    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    slopes = [(ys[i + 1] - ys[i]) / dx[i] for i in range(n - 1)]

    # Tangents: harmonic mean of neighboring slopes; zero at local extrema
    # (sign change) so the curve doesn't overshoot.
    tangents = [slopes[0]]
    for i in range(1, n - 1):
        if slopes[i - 1] * slopes[i] <= 0:
            tangents.append(0.0)
        else:
            tangents.append(2 / (1 / slopes[i - 1] + 1 / slopes[i]))
    tangents.append(slopes[-1])

    points: list[tuple[float, float]] = []
    for i in range(n - 1):
        for s in range(samples_per_segment):
            t = s / samples_per_segment
            h00 = (1 + 2 * t) * (1 - t) ** 2
            h10 = t * (1 - t) ** 2
            h01 = t * t * (3 - 2 * t)
            h11 = t * t * (t - 1)
            x = xs[i] + t * dx[i]
            y = (
                h00 * ys[i]
                + h10 * dx[i] * tangents[i]
                + h01 * ys[i + 1]
                + h11 * dx[i] * tangents[i + 1]
            )
            points.append((x, y))
    points.append((xs[-1], ys[-1]))
    return points
