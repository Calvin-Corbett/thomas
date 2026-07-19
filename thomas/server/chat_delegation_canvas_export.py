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


def _prompt_data(prompt: str) -> list[ChartDatum]:
    rows: list[ChartDatum] = []
    blocked = {"chart", "graph", "plot", "show", "make", "create", "draw", "line", "bar", "pie"}
    for match in _PAIR_RE.finditer(str(prompt or "")):
        label = match.group(1).strip()
        if label.casefold() in blocked:
            continue
        value = float(match.group(2))
        if match.group(3):
            label = f"{label} (%)"
        if not any(row.label.casefold() == label.casefold() for row in rows):
            rows.append(ChartDatum(label=label, value=value))
    return rows[:16]


def extract_chart_data(prompt: str, plan: str) -> tuple[str, list[ChartDatum]]:
    spec = _plan_object(plan)
    title = str(spec.get("title") or "").strip() or "Thomas chart"
    rows = _prompt_data(prompt)
    if rows:
        return title, rows
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
    note = re.sub(r"\s+", " ", prompt).strip()[:110]
    pdf.drawString(52, 44, note)
    pdf.drawRightString(740, 44, "Source data included beside this PDF")
    pdf.showPage()
    pdf.save()


def export_static_chart(work_dir: str | Path, *, prompt: str, plan: str) -> list[str]:
    """Write PDF and source data, failing closed when the required PDF runtime is absent."""

    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    title, rows = extract_chart_data(prompt, plan)
    pdf_path = root / "chart.pdf"
    csv_path = root / "chart-data.csv"
    _write_pdf(pdf_path, title, prompt, rows, _chart_kind(prompt))
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["label", "value"])
        writer.writerows((row.label, f"{row.value:g}") for row in rows)
    created = [pdf_path.name, csv_path.name]
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
    if not pdf_path.read_bytes().startswith(b"%PDF-") or csv_path.stat().st_size < 10:
        raise OSError("chart export readback failed")
    return created


__all__ = [
    "ChartDatum",
    "ChartExportUnavailable",
    "export_static_chart",
    "extract_chart_data",
    "is_static_chart_request",
]
