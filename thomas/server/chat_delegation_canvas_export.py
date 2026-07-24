"""Reviewed static-chart exports for Canvas delegations."""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ChartDatum:
    label: str
    value: float


class ChartExportUnavailable(RuntimeError):
    """Raised when Thomas cannot produce the required reviewed PDF honestly."""


_CHART_RE = re.compile(r"\b(?:bar|line|pie|donut|scatter|area)?\s*(?:chart|graph|plot)\b", re.I)
_INTERACTIVE_RE = re.compile(
    r"\b(?:interactive|dashboard|game|app|site|website|simulator|hover|tooltip|filter|zoom|pan|"
    r"drill[- ]?down|click(?:able)?|drag(?:gable)?|toggle|selector|dropdown)\b",
    re.I,
)
_PAIR_RE = re.compile(
    r"(?<![\w.])([A-Za-z][A-Za-z0-9_-]{0,23})\s*(?::|=|-)?\s*\$?(-?\d+(?:\.\d+)?)\s*(%)?",
    re.I,
)


def is_static_chart_request(prompt: str) -> bool:
    text = str(prompt or "")
    return bool(_CHART_RE.search(text)) and not bool(_INTERACTIVE_RE.search(text))


def _plan_object(plan: str) -> dict[str, Any]:
    try:
        value = json.loads(str(plan or ""))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


# Function words are never data labels. Without this, "the most popular
# programming languages in 2026" scrapes as the single row `in = 2026`, and
# because prompt data outranks the rendered plan, the exported CSV and
# spreadsheet then describe that instead of the seven bars actually drawn.
# A person opening the backing data for their chart found one row reading
# "in, 2026".
_NON_LABEL_TEXT = """
chart graph plot show make create draw line bar pie
a an the of in on at to for from by with and or as is are was were be been
this that these those it its into onto up down out off over under near per
about above below after before during since until within through between
top best most least more less than then vs versus around approximately
year years month months day days week weeks time times
"""
_NON_LABEL_WORDS = frozenset(_NON_LABEL_TEXT.split())
_NOISE_BLOCK_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _prompt_data(prompt: str) -> list[ChartDatum]:
    rows: list[ChartDatum] = []
    for match in _PAIR_RE.finditer(str(prompt or "")):
        label = match.group(1).strip()
        if label.casefold() in _NON_LABEL_WORDS:
            continue
        value = float(match.group(2))
        if match.group(3):
            label = f"{label} (%)"
        if not any(row.label.casefold() == label.casefold() for row in rows):
            rows.append(ChartDatum(label=label, value=value))
    return rows[:16]


# A label followed by its value in the chart the user is looking at, e.g.
# "Electricity · 45%", "Natural gas: 35", "LPG / propane — 8%".
# "#" and "." belong in labels: C#, .NET, Node.js are data, not punctuation.
_RENDERED_PAIR_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9 /&'#.+-]{0,38}?)\s*[·:=–—-]\s*(-?\d+(?:\.\d+)?)\s*%?"
    r"|([A-Za-z][A-Za-z0-9 /&'#.+-]{0,38}?)\s+(-?\d+(?:\.\d+)?)\s*%",
)


def _rendered_data(html: str) -> list[ChartDatum]:
    """Read the chart's own labels and values out of what was rendered.

    The plan is an intermediate; the rendered document is the thing the user is
    actually looking at. Deriving backing data from anything else is how a chart
    showing Electricity 45% and Natural gas 35% shipped a spreadsheet reading
    "Series 1, 100".
    """
    text = str(html or "")
    if not text.strip():
        return []
    text = _NOISE_BLOCK_RE.sub(" ", text)
    text = " ".join(_TAG_STRIP_RE.sub(" ", text).split())
    found: list[tuple[str, float, bool]] = []
    for match in _RENDERED_PAIR_RE.finditer(text):
        label = (match.group(1) or match.group(3) or "").strip(" -·:=")
        raw_value = match.group(2) or match.group(4)
        if not label or raw_value is None:
            continue
        label = _trim_to_label(label)
        if not label:
            continue
        try:
            value = float(raw_value)
        except ValueError:
            continue
        found.append((label, value, "%" in match.group(0)))

    # Chart rows share a format. When most carry a percent sign, the ones that
    # do not are prose -- the heading "Household Energy Use by Source - 2026"
    # otherwise reads as the data point Source = 2026.
    percent_rows = [row for row in found if row[2]]
    if len(percent_rows) >= 2:
        found = percent_rows

    rows: list[ChartDatum] = []
    for label, value, _ in found:
        if any(row.label.casefold() == label.casefold() for row in rows):
            continue
        rows.append(ChartDatum(label=label, value=value))
    # One pair is far more likely to be prose than a chart.
    return rows[:16] if len(rows) >= 2 else []


def _trim_to_label(raw: str) -> str:
    """Reduce a matched run back to the label itself.

    The pattern can reach backwards across surrounding prose, so
    "...annual household site energy use Electricity" arrives whole. A chart
    label starts at a capital, so keep the trailing run from the last capitalised
    word onward: that yields "Electricity", while "Natural gas" and
    "LPG / propane" survive intact.
    """
    words = raw.split()
    if not words:
        return ""
    start = 0
    for index, word in enumerate(words):
        if word[:1].isupper():
            start = index
    words = words[start:]
    while words and words[0].casefold() in _NON_LABEL_WORDS:
        words.pop(0)
    if not words or len(words) > 4:
        return ""
    if all(word.casefold() in _NON_LABEL_WORDS for word in words):
        return ""
    return " ".join(words)


def extract_chart_data(prompt: str, plan: str, rendered_html: str = "") -> tuple[str, list[ChartDatum]]:
    spec = _plan_object(plan)
    title = str(spec.get("title") or "").strip() or "Thomas chart"
    rows = _prompt_data(prompt)
    if rows:
        return title, rows
    # Prefer what was drawn over what was planned.
    rendered = _rendered_data(rendered_html)
    if rendered:
        return title, rendered
    elements = spec.get("elements") if isinstance(spec.get("elements"), list) else []
    numbers = [row for row in elements if isinstance(row, dict) and row.get("kind") == "number"]
    for index, row in enumerate(numbers[:16], 1):
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        rows.append(ChartDatum(label=str(row.get("label") or f"Series {index}"), value=value))
    if not rows:
        bars = [row for row in elements if isinstance(row, dict) and row.get("kind") == "bar"]
        for index, row in enumerate(bars[:16], 1):
            geometry = row.get("geometry") if isinstance(row.get("geometry"), dict) else {}
            value = float(geometry.get("h") or geometry.get("w") or 0)
            rows.append(ChartDatum(label=str(row.get("label") or f"Series {index}"), value=value))
    return title, rows or [ChartDatum(label="Series 1", value=1.0)]


def _clean_note(prompt: str) -> str:
    """Footer caption from the user's own request, minus any appended handoff.

    A referential follow-up ("rerun the chart") is threaded with a recent-
    conversation handoff for the worker; that preamble must not bleed into the
    chart's footer caption.
    """
    head = str(prompt or "").split("\n\n", 1)[0]
    return re.sub(r"\s+", " ", head).strip()[:110]


def _chart_kind(prompt: str) -> str:
    match = re.search(r"\b(bar|line|pie|donut|scatter|area)\s+(?:chart|graph|plot)\b", str(prompt or ""), re.I)
    return match.group(1).lower() if match else "bar"


def _palette(index: int) -> tuple[float, float, float]:
    colors = ((0.22, 0.35, 0.95), (0.15, 0.70, 0.62), (0.55, 0.38, 0.95), (0.95, 0.48, 0.30), (0.22, 0.58, 0.92))
    return colors[index % len(colors)]


def _draw_cartesian(canvas: Any, rows: list[ChartDatum], *, kind: str) -> None:
    left, bottom, width, height = 78.0, 112.0, 638.0, 330.0
    canvas.setStrokeColorRGB(0.83, 0.86, 0.92)
    canvas.setLineWidth(0.8)
    for step in range(6):
        y = bottom + height * step / 5
        canvas.line(left, y, left + width, y)
    values = [row.value for row in rows]
    low = min(0.0, min(values))
    high = max(values)
    span = high - low or 1.0
    baseline = bottom + height * (0 - low) / span
    slot = width / max(1, len(rows))
    points: list[tuple[float, float]] = []
    for index, row in enumerate(rows):
        x = left + slot * (index + 0.5)
        y = bottom + height * (row.value - low) / span
        points.append((x, y))
        canvas.setFillColorRGB(0.30, 0.34, 0.43)
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(x, bottom - 20, row.label[:18])
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawCentredString(x, y + 9, f"{row.value:g}")
        if kind == "bar":
            bar_width = min(46.0, slot * 0.62)
            color = _palette(index)
            canvas.setFillColorRGB(*color)
            canvas.roundRect(
                x - bar_width / 2, min(y, baseline), bar_width, abs(y - baseline) or 2, 5, fill=1, stroke=0
            )
    if kind != "bar":
        canvas.setStrokeColorRGB(0.22, 0.35, 0.95)
        canvas.setLineWidth(3)
        for start, end in zip(points, points[1:], strict=False):
            canvas.line(start[0], start[1], end[0], end[1])
        for index, (x, y) in enumerate(points):
            canvas.setFillColorRGB(*_palette(index))
            canvas.circle(x, y, 5, fill=1, stroke=0)


def _draw_pie(canvas: Any, rows: list[ChartDatum], *, donut: bool) -> None:
    total = sum(abs(row.value) for row in rows) or 1.0
    start = 90.0
    for index, row in enumerate(rows):
        extent = 360.0 * abs(row.value) / total
        canvas.setFillColorRGB(*_palette(index))
        canvas.wedge(92, 105, 442, 455, start, extent, fill=1, stroke=0)
        start += extent
    if donut:
        canvas.setFillColorRGB(1, 1, 1)
        canvas.circle(267, 280, 78, fill=1, stroke=0)
    for index, row in enumerate(rows):
        y = 407 - index * 29
        canvas.setFillColorRGB(*_palette(index))
        canvas.roundRect(495, y, 14, 14, 3, fill=1, stroke=0)
        canvas.setFillColorRGB(0.16, 0.19, 0.26)
        canvas.setFont("Helvetica", 10)
        canvas.drawString(518, y + 2, f"{row.label[:24]}  {row.value:g}")


def _write_pdf(path: Path, title: str, prompt: str, rows: list[ChartDatum], kind: str) -> None:
    try:
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.pdfgen import canvas as reportlab_canvas
    except ImportError as exc:
        raise ChartExportUnavailable(
            "PDF chart export is unavailable because the required reportlab package is not installed"
        ) from exc

    pdf = reportlab_canvas.Canvas(str(path), pagesize=landscape(letter), pageCompression=1)
    pdf.setTitle(title)
    pdf.setAuthor("Thomas")
    pdf.setFillColorRGB(0.07, 0.09, 0.15)
    pdf.rect(0, 545, 792, 67, fill=1, stroke=0)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setFont("Helvetica-Bold", 22)
    pdf.drawString(52, 574, title[:72])
    pdf.setFillColorRGB(0.68, 0.73, 0.84)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(52, 558, "Reviewed Thomas Canvas export")
    if kind in {"pie", "donut"}:
        _draw_pie(pdf, rows, donut=kind == "donut")
    else:
        _draw_cartesian(pdf, rows, kind=kind)
    pdf.setFillColorRGB(0.35, 0.39, 0.48)
    pdf.setFont("Helvetica", 8)
    note = _clean_note(prompt)
    pdf.drawString(52, 44, note)
    pdf.drawRightString(740, 44, "Source data included beside this PDF")
    pdf.showPage()
    pdf.save()


def _chart_format(prompt: str) -> str:
    """Honor an explicit output-format request; default to the reviewed PDF."""
    text = str(prompt or "").lower()
    if re.search(r"\bpngs?\b", text) and not re.search(r"\bpdf\b", text):
        return "png"
    return "pdf"


def _palette255(index: int) -> tuple[int, int, int]:
    r, g, b = _palette(index)
    return (round(r * 255), round(g * 255), round(b * 255))


def _png_font(size: int, *, bold: bool = False) -> Any:
    from PIL import ImageFont

    names = ("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "DejaVuSans.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _write_png(path: Path, title: str, prompt: str, rows: list[ChartDatum], kind: str) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ChartExportUnavailable(
            "PNG chart export is unavailable because the required Pillow package is not installed"
        ) from exc

    width, height = 1000, 620
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 70], fill=(18, 23, 38))
    draw.text((36, 22), title[:64], fill=(255, 255, 255), font=_png_font(28, bold=True))
    draw.text((36, 52), "Reviewed Thomas Canvas export", fill=(174, 186, 214), font=_png_font(12))

    if kind in {"pie", "donut"}:
        _draw_pie_png(draw, rows, donut=kind == "donut")
    else:
        _draw_cartesian_png(draw, rows, kind=kind)

    note = _clean_note(prompt)
    draw.text((36, height - 30), note, fill=(90, 99, 122), font=_png_font(11))
    img.save(str(path), "PNG")


def _draw_cartesian_png(draw: Any, rows: list[ChartDatum], *, kind: str) -> None:
    left, top, right, bottom = 96.0, 120.0, 952.0, 512.0
    plot_h = bottom - top
    small = _png_font(12)
    small_bold = _png_font(12, bold=True)
    for step in range(6):
        y = bottom - plot_h * step / 5
        draw.line([(left, y), (right, y)], fill=(212, 219, 235), width=1)
    values = [row.value for row in rows]
    low = min(0.0, min(values))
    high = max(values)
    span = high - low or 1.0
    baseline = bottom - plot_h * (0 - low) / span
    slot = (right - left) / max(1, len(rows))
    points: list[tuple[float, float]] = []
    for index, row in enumerate(rows):
        cx = left + slot * (index + 0.5)
        vy = bottom - plot_h * (row.value - low) / span
        points.append((cx, vy))
        draw.text((cx, bottom + 8), row.label[:16], fill=(70, 78, 98), font=small, anchor="ma")
        draw.text((cx, vy - 16), f"{row.value:g}", fill=(40, 46, 64), font=small_bold, anchor="ms")
        if kind == "bar":
            bw = min(56.0, slot * 0.62)
            draw.rounded_rectangle(
                [cx - bw / 2, min(vy, baseline), cx + bw / 2, max(vy, baseline)],
                radius=6,
                fill=_palette255(index),
            )
    if kind != "bar":
        for start, end in zip(points, points[1:], strict=False):
            draw.line([start, end], fill=(56, 89, 242), width=3)
        for index, (cx, vy) in enumerate(points):
            draw.ellipse([cx - 5, vy - 5, cx + 5, vy + 5], fill=_palette255(index))


def _draw_pie_png(draw: Any, rows: list[ChartDatum], *, donut: bool) -> None:
    cx, cy, radius = 300.0, 330.0, 175.0
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    total = sum(abs(row.value) for row in rows) or 1.0
    start = -90.0
    for index, row in enumerate(rows):
        extent = 360.0 * abs(row.value) / total
        draw.pieslice(bbox, start, start + extent, fill=_palette255(index))
        start += extent
    if donut:
        inner = radius * 0.5
        draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner], fill=(255, 255, 255))
    legend = _png_font(13)
    for index, row in enumerate(rows):
        y = 150 + index * 30
        draw.rounded_rectangle([560, y, 576, y + 16], radius=3, fill=_palette255(index))
        draw.text((588, y + 1), f"{row.label[:24]}  {row.value:g}", fill=(40, 48, 66), font=legend)


def export_static_chart(
    work_dir: str | Path, *, prompt: str, plan: str, rendered_html: str = ""
) -> list[str]:
    """Write the chart (honoring an explicit PNG request) plus source data.

    Fails closed when the chosen renderer's runtime is absent, falling back to
    the reviewed PDF when PNG rendering is unavailable.

    ``rendered_html`` is the document the user is actually looking at; its own
    labels and values are the truest source for the backing data that ships
    beside it.
    """

    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    title, rows = extract_chart_data(prompt, plan, rendered_html)
    kind = _chart_kind(prompt)
    csv_path = root / "chart-data.csv"

    primary_name = "chart.pdf"
    if _chart_format(prompt) == "png":
        try:
            _write_png(root / "chart.png", title, prompt, rows, kind)
            primary_name = "chart.png"
        except ChartExportUnavailable:
            primary_name = "chart.pdf"
    if primary_name == "chart.pdf":
        _write_pdf(root / "chart.pdf", title, prompt, rows, kind)
    primary_path = root / primary_name

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["label", "value"])
        writer.writerows((row.label, f"{row.value:g}") for row in rows)
    created = [primary_name, csv_path.name]
    try:
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = "Chart data"
        sheet.append(["Label", "Value"])
        for row in rows:
            sheet.append([row.label, row.value])
        sheet.freeze_panes = "A2"
        sheet.column_dimensions["A"].width = 26
        sheet.column_dimensions["B"].width = 14
        xlsx_path = root / "chart-data.xlsx"
        book.save(xlsx_path)
        created.append(xlsx_path.name)
    except (ImportError, OSError, ValueError):
        pass

    magic = b"\x89PNG" if primary_name == "chart.png" else b"%PDF-"
    if not primary_path.read_bytes().startswith(magic) or csv_path.stat().st_size < 10:
        raise OSError("chart export readback failed")
    return created


__all__ = [
    "ChartDatum",
    "ChartExportUnavailable",
    "export_static_chart",
    "extract_chart_data",
    "is_static_chart_request",
]
