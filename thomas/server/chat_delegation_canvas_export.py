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
# A bar's axis label sits under that bar. On the 720x520 stage a bar column is
# rarely under ~40px wide, so a label further than this horizontally belongs to
# a different bar and is not borrowed.
_LABEL_COLUMN_TOLERANCE_PX = 60.0
# Rows in a horizontal bar chart are far further apart than a label's own
# height, so this only needs to absorb baseline drift between a value and the
# category name beside it -- not to reach the next bar.
_LABEL_ROW_TOLERANCE_PX = 24.0
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


# Words that are never data labels. Without this, "the most popular languages
# in 2026" scrapes as the single row `in = 2026`, and because prompt data
# outranks everything the exported CSV, spreadsheet and PDF all describe that
# instead of the chart. Someone opening the data behind their chart found one
# row reading "in, 2026".
_NON_LABEL_TEXT = """
chart graph plot show make create draw line bar pie
a an the of in on at to for from by with and or as is are was were be been
this that these those it its into onto up down out off over under near per
about above below after before during since until within through between
top best most least more less than then vs versus around approximately
year years month months day days week weeks time times last next across
"""
_NON_LABEL_WORDS = frozenset(_NON_LABEL_TEXT.split())

# A single scraped pair is prose, not a dataset. "bar chart of CO2 emissions"
# yields one row (CO = 2) and "the last 10 years" yields another (last = 10);
# either one used to outrank the entire rendered chart and ship as its data.
# Real supplied data comes in series -- "Q1 120 Q2 135" -- so require at least
# two rows before believing the prompt over the plan.
_MIN_PROMPT_ROWS = 2


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
    return rows[:16] if len(rows) >= _MIN_PROMPT_ROWS else []


def _point(element: Any) -> tuple[float, float] | None:
    """The plan's own declared position for an element, if it gave one."""
    if not isinstance(element, dict):
        return None
    geometry = element.get("geometry")
    if not isinstance(geometry, dict):
        return None
    try:
        return float(geometry.get("x")), float(geometry.get("y"))
    except (TypeError, ValueError):
        return None


_PRINTED_VALUE_RE = re.compile(r"^[$€£]?\s*(-?\d{1,3}(?:,\d{3})+|-?\d+(?:\.\d+)?)\s*%?$")


def _printed_value(text: str) -> float | None:
    """The number a value label prints, or None if it is not purely a number.

    The WHOLE string must be the number. "68.7%" and "1,528" are values;
    "Workers age 16+, 2022" and "Q1" are not, so a caption that merely contains
    a year cannot become a data point.
    """
    match = _PRINTED_VALUE_RE.match(str(text or "").strip())
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _text_elements(elements: list[Any]) -> list[tuple[float, float, str]]:
    """Every positioned `text` element as (x, y, label)."""
    out: list[tuple[float, float, str]] = []
    for element in elements:
        if not isinstance(element, dict) or element.get("kind") != "text":
            continue
        label = str(element.get("label") or "").strip()
        point = _point(element)
        if label and point is not None:
            out.append((point[0], point[1], label))
    return out


def _reading_order(placed: list[tuple[int, float, float]]) -> list[int]:
    """Row indices in the order a reader meets them in the drawn chart.

    Plan-element order is NOT reading order. The planner emitted the English bar
    last, so a correctly paired export still listed English (1528, the tallest
    bar and the first one drawn) beneath Arabic (335) -- the numbers were right
    and the table still read as wrong.

    Which axis to sort on cannot be assumed, because the coordinate that varies
    with the VALUE differs by chart orientation: in a column chart the value
    label rides up and down with the bar, so y is meaningless and x is the
    stable axis; in a horizontal bar chart it is the reverse. Sorting on the
    wrong one silently orders the table by magnitude instead of by category.
    So this sorts on the CATEGORY labels, and picks the axis those labels
    actually spread along.
    """
    if len(placed) < 2:
        return [index for index, _x, _y in placed]
    xs = [x for _i, x, _y in placed]
    ys = [y for _i, _x, y in placed]
    spread_x = max(xs) - min(xs)
    spread_y = max(ys) - min(ys)
    if spread_x >= spread_y:
        return [i for i, _x, _y in sorted(placed, key=lambda p: (p[1], p[2]))]
    return [i for i, _x, _y in sorted(placed, key=lambda p: (p[2], p[1]))]


def _category_names(
    elements: list[Any], numbers: list[dict[str, Any]]
) -> dict[int, tuple[str, float, float]]:
    """Recover each value's category name from the neighbouring axis label.

    In this plan format a bar chart's categories are NOT stored on the number
    elements -- the planner is told "value labels sit just above each bar, axis
    labels just below", so the value is a `number` and the name it belongs to is
    a separate `text` element under the same bar. Reading only `number` elements
    therefore yields five real values and zero names, and the export shipped
    "Series 1..5" -- a chart of banana varieties naming no bananas.

    Values are NEVER derived here. Only the name is recovered, by pairing on the
    coordinates the planner itself declared. An earlier attempt to read values
    out of rendered bar geometry corrupted the data (CSS pixel heights exported
    under real category names) and was reverted; this stays clear of that by
    treating geometry as an index into the plan, never as data.
    """
    texts = [t for t in _text_elements(elements) if _printed_value(t[2]) is None]
    return _category_names_for(texts, [_point(number) for number in numbers])


def _category_names_for(
    texts: list[tuple[float, float, str]],
    origins: list[tuple[float, float] | None],
) -> dict[int, tuple[str, float, float]]:
    """Pair each origin with the category label that belongs to it."""
    if not texts:
        return {}

    names: dict[int, tuple[str, float, float]] = {}
    claimed: set[int] = set()
    for index, origin in enumerate(origins):
        if origin is None:
            continue
        # Both orientations have to work, and they hide the label in different
        # places. A column chart puts the category tick BELOW the value, sharing
        # its x. A horizontal bar chart puts it to the LEFT, sharing its y --
        # and there the value label slides sideways with the bar, so the two can
        # be hundreds of pixels apart in x and still belong together. Looking
        # only down a column left every horizontal chart labelled "Series N".
        best: int | None = None
        best_cost: float | None = None
        for i, (tx, ty, _text) in enumerate(texts):
            if i in claimed:
                continue
            cost: float | None = None
            if ty > origin[1] and abs(tx - origin[0]) <= _LABEL_COLUMN_TOLERANCE_PX:
                cost = abs(tx - origin[0])
            if tx < origin[0] and abs(ty - origin[1]) <= _LABEL_ROW_TOLERANCE_PX:
                row_cost = abs(ty - origin[1])
                cost = row_cost if cost is None else min(cost, row_cost)
            if cost is None:
                continue
            if best_cost is None or cost < best_cost:
                best, best_cost = i, cost
        # A label three bars away is not this bar's label -- an honest
        # placeholder beats a confidently wrong name.
        if best is None:
            continue
        claimed.add(best)
        names[index] = (texts[best][2], texts[best][0], texts[best][1])
    return names


_LEGEND_ROW_RE = re.compile(
    r"^(?P<name>[^\d•·|][^•·|]*?)"          # a category name, not starting with a digit
    r"\s{1,}(?P<value>-?\d{1,3}(?:,\d{3})*(?:\.\d+)?)"  # its value
    r"\s*%?"                                 # which may itself be a percentage
    r"(?:\s*[•·|,–-]\s*-?[\d.,]+\s*%?)?$"   # and may be followed by a share
)
# Legend entries sit in one column; this is the drift allowed within it.
_LEGEND_COLUMN_TOLERANCE_PX = 14.0


def _legend_rows(elements: list[Any]) -> list[ChartDatum]:
    """Rows from a legend that prints "Electricity  5.2 • 48.6%" as one string.

    A donut or pie states its categories in a legend beside the ring, with the
    name and the figure in a single text element, and puts only the TOTAL in the
    middle as a number. Reading number elements alone therefore found one row
    (the total, correctly rejected as "a chart of one") and the real breakdown
    was never exported at all.

    Two guards keep a caption from becoming data: the string must END with its
    figure, and at least two such strings must share one column -- a legend is
    a column, a stray sentence is not. So "…EIA Annual Energy Outlook 2023
    residential sector data." is skipped despite containing years.
    """
    candidates: list[tuple[float, float, str, float]] = []
    for x, y, text in _text_elements(elements):
        match = _LEGEND_ROW_RE.match(text)
        if not match:
            continue
        name = match.group("name").strip(" \t:-–—")
        if not name or not any(ch.isalpha() for ch in name):
            continue
        try:
            value = float(match.group("value").replace(",", ""))
        except ValueError:
            continue
        candidates.append((x, y, name, value))

    columns: dict[int, list[tuple[float, float, str, float]]] = {}
    for entry in candidates:
        key = int(entry[0] // _LEGEND_COLUMN_TOLERANCE_PX)
        columns.setdefault(key, []).append(entry)
        if key:  # tolerate an entry straddling a bucket boundary
            columns.setdefault(key - 1, []).append(entry)
    best = max(columns.values(), key=len, default=[])
    if len(best) < _MIN_PROMPT_ROWS:
        return []
    seen: set[tuple[float, float]] = set()
    unique = []
    for x, y, name, value in sorted(best, key=lambda e: (e[1], e[0])):
        if (x, y) in seen:
            continue
        seen.add((x, y))
        unique.append(ChartDatum(label=name, value=value))
    return unique[:16]


def _printed_rows(elements: list[Any]) -> list[ChartDatum]:
    """Values a plan PRINTS as text rather than declaring as `number` elements.

    Plans routinely write the value label as text -- "68.7%" above "Drive
    alone" -- and declare no `number` element at all. Refusing to read those
    left a chart of real, visible data with no data file beside it.

    This is transcription, not inference: the figure returned is the figure the
    chart displays. That is the line separating it from the reverted attempt to
    read values out of bar geometry, where 24 pixels of height was reported as
    the value 24.

    Axis ticks print as numbers too ("1,500", "1,000", "500", "0"). They are
    excluded for free by requiring a value to pair with a CATEGORY label: ticks
    sit in their own column with no category beneath them, so they never pair.
    """
    texts = _text_elements(elements)
    values = [(x, y, _printed_value(t)) for x, y, t in texts]
    candidates = [(x, y, v) for x, y, v in values if v is not None]
    labels = [(x, y, t) for (x, y, t), (_x, _y, v) in zip(texts, values) if v is None]
    if len(candidates) < _MIN_PROMPT_ROWS or not labels:
        return []

    names = _category_names_for(labels, [(x, y) for x, y, _v in candidates])
    rows: list[ChartDatum] = []
    placed: list[tuple[int, float, float]] = []
    for index, (_x, _y, value) in enumerate(candidates[:16]):
        paired = names.get(index)
        if paired is None:
            continue  # an axis tick, or a stray figure in a caption
        placed.append((len(rows), paired[1], paired[2]))
        rows.append(ChartDatum(label=paired[0], value=float(value)))
    if len(rows) < _MIN_PROMPT_ROWS:
        return []
    return [rows[i] for i in _reading_order(placed)]


def _declared_rows(spec: dict[str, Any]) -> list[ChartDatum]:
    """The series the planner stated outright, in its own `data` block.

    Preferred over every other path here, because the rest of this module
    reverse-engineers the numbers back out of the DRAWING -- pairing value
    labels to axis labels by pixel coordinates. That works until the next plan
    draws the same chart differently (bar+number, bar+text, a donut legend as
    one string, a donut legend as two elements), and each new shape needs its
    own rule while the previous one quietly stops matching. Asked directly, the
    planner just writes the series down.
    """
    declared = spec.get("data")
    if not isinstance(declared, list):
        return []
    rows: list[ChartDatum] = []
    for entry in declared[:16]:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label") or "").strip()
        raw = entry.get("value")
        if isinstance(raw, str):
            raw = _printed_value(raw)  # tolerate "5.2" or "48%" slipping through
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not label or math.isnan(value) or math.isinf(value):
            continue
        rows.append(ChartDatum(label=label, value=value))
    return rows if len(rows) >= _MIN_PROMPT_ROWS else []


def extract_chart_data(prompt: str, plan: str) -> tuple[str, list[ChartDatum]]:
    spec = _plan_object(plan)
    title = str(spec.get("title") or "").strip() or "Thomas chart"
    rows = _prompt_data(prompt)
    if rows:
        return title, rows
    declared = _declared_rows(spec)
    if declared:
        return title, declared
    elements = spec.get("elements") if isinstance(spec.get("elements"), list) else []
    numbers = [row for row in elements if isinstance(row, dict) and row.get("kind") == "number"]
    names = _category_names(elements, numbers)
    placed: list[tuple[int, float, float]] = []
    for index, row in enumerate(numbers[:16], 1):
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        paired = names.get(index - 1)
        label = str(row.get("label") or "").strip() or (paired[0].strip() if paired else "")
        if paired is not None:
            placed.append((len(rows), paired[1], paired[2]))
        rows.append(ChartDatum(label=label or f"Series {index}", value=value))
    # Emit in the order the chart is read, not the order the planner happened to
    # emit its elements. Only reorder when every row's position is known, so a
    # partially-paired plan is never shuffled on incomplete information.
    if len(placed) == len(rows) and len(rows) > 1:
        rows = [rows[i] for i in _reading_order(placed)]
    if not rows:
        rows = _printed_rows(elements)
    if len(rows) < _MIN_PROMPT_ROWS:
        # A donut puts only its TOTAL in the middle and its categories in a
        # legend beside the ring, so the number path finds exactly one row.
        rows = _legend_rows(elements) or rows
    if len(rows) < _MIN_PROMPT_ROWS:
        # A chart of one bar is not a chart. When the model hedges -- Calvin's
        # "how people commute" came back as a single 100% bar subtitled
        # "Illustrative distribution", and his household-energy chart as the
        # lone row `Series 1, 100` -- attaching a one-row spreadsheet dresses
        # that hedge up as a finding. The rendered chart still ships; the data
        # file does not.
        rows = []
    # When the plan draws a chart with `bar` elements and no `number` elements,
    # there is no data here -- only a picture of one. This used to fall back to
    # the bars' pixel geometry and then, failing that, to a literal
    # ChartDatum("Series 1", 1.0). Both are inventions, and both shipped under a
    # "verified" badge with backing data files attached. Asking for the most
    # spoken languages returned eight rows reading `Series N, 24` -- eight bars,
    # 24 pixels each. A reader cannot tell that from a real measurement.
    #
    # No rows is the honest answer. The caller delivers the chart the user can
    # actually see and omits the data files rather than fabricating them.
    return title, rows


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


def export_static_chart(work_dir: str | Path, *, prompt: str, plan: str) -> list[str]:
    """Write the chart (honoring an explicit PNG request) plus source data.

    Fails closed when the chosen renderer's runtime is absent, falling back to
    the reviewed PDF when PNG rendering is unavailable.
    """

    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    title, rows = extract_chart_data(prompt, plan)
    if not rows:
        # Nothing here is measurable. Writing a PDF and a spreadsheet anyway is
        # what produced "verified" deliverables containing invented series.
        raise ChartExportUnavailable(
            "the reviewed plan carries no chart values, only a drawing of them"
        )
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
