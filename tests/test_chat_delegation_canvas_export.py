from __future__ import annotations

import builtins
import csv
import json
from pathlib import Path

import pytest

from thomas.server.chat_delegation_canvas_export import (
    ChartExportUnavailable,
    _chart_format,
    _clean_note,
    export_static_chart,
    extract_chart_data,
    is_static_chart_request,
)
from thomas.server.chat_delegation_canvas_intent import is_canvas_task


def _plan() -> str:
    return json.dumps(
        {
            "title": "Quarterly Revenue",
            "elements": [
                {"kind": "number", "label": "Q1", "value": 120},
                {"kind": "number", "label": "Q2", "value": 135},
            ],
        }
    )


def test_static_chart_classification_keeps_interactive_html_primary() -> None:
    assert is_static_chart_request("Create a bar chart showing Q1 120 and Q2 135")
    assert not is_static_chart_request("Create an interactive chart dashboard")
    assert not is_static_chart_request("Build a chart game")
    assert not is_static_chart_request("Create a chart with hover tooltips")
    assert not is_static_chart_request("Create a chart users can filter and zoom")


def test_chart_data_preserves_user_values() -> None:
    title, rows = extract_chart_data("Quarterly revenue chart Q1 120 Q2 135", _plan())

    assert title == "Quarterly Revenue"
    assert [(row.label, row.value) for row in rows] == [("Q1", 120.0), ("Q2", 135.0)]


def test_a_stray_word_and_number_in_the_request_is_not_chart_data() -> None:
    """The backing data must describe the chart, not the sentence that asked for
    it. Prompt data outranks everything, so a single scraped pair used to become
    the whole dataset: "languages in 2026" shipped as `in,2026`, and "CO2
    emissions" as `CO,2`. Real supplied data arrives as a series."""
    plan = json.dumps(
        {
            "title": "Most Spoken Languages",
            "elements": [
                {"kind": "number", "label": "English", "value": 1528},
                {"kind": "number", "label": "Mandarin", "value": 1184},
            ],
        }
    )

    for request in (
        "make me a graph of the most popular languages in 2026",
        "bar chart of CO2 emissions by sector",
        "chart the last 10 years of Apple revenue",
    ):
        title, rows = extract_chart_data(request, plan)
        assert title == "Most Spoken Languages"
        assert [(row.label, row.value) for row in rows] == [
            ("English", 1528.0),
            ("Mandarin", 1184.0),
        ], request


def test_a_real_supplied_series_still_outranks_the_plan() -> None:
    """The reason prompt data is consulted at all: numbers the user typed are
    the numbers they want charted."""
    _title, rows = extract_chart_data("bar chart Alpha 3, Beta 7, Gamma 5", _plan())

    assert [(row.label, row.value) for row in rows] == [
        ("Alpha", 3.0),
        ("Beta", 7.0),
        ("Gamma", 5.0),
    ]


def test_export_static_chart_writes_pdf_and_backing_data(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    files = export_static_chart(
        tmp_path,
        prompt="Create a bar chart showing Q1 120 and Q2 135",
        plan=_plan(),
    )

    assert files[:2] == ["chart.pdf", "chart-data.csv"]
    assert (tmp_path / "chart.pdf").read_bytes().startswith(b"%PDF-")
    with (tmp_path / "chart-data.csv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle)) == [["label", "value"], ["Q1", "120"], ["Q2", "135"]]
    if "chart-data.xlsx" in files:
        assert (tmp_path / "chart-data.xlsx").stat().st_size > 1000


def test_clean_note_strips_appended_handoff() -> None:
    # A rerun follow-up is threaded with a handoff for the worker; the footer
    # caption must show only the user's request, not the handoff preamble.
    threaded = "rerun the chart\n\nFor context, here is the recent conversation between the user and Thomas"
    assert _clean_note(threaded) == "rerun the chart"
    assert _clean_note("make a bar chart of jan 100 feb 200") == "make a bar chart of jan 100 feb 200"


def test_chart_format_honors_explicit_png() -> None:
    assert _chart_format("make a downloadable png bar chart") == "png"
    assert _chart_format("make a bar chart") == "pdf"
    # An explicit pdf mention wins over png to avoid surprising a pdf-wanting user.
    assert _chart_format("png or pdf, either is fine") == "pdf"


def test_export_static_chart_honors_png_request(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    files = export_static_chart(
        tmp_path,
        prompt="Make a downloadable PNG bar chart: Q1 120, Q2 135",
        plan=_plan(),
    )
    assert files[0] == "chart.png"
    assert "chart-data.csv" in files
    assert (tmp_path / "chart.png").read_bytes().startswith(b"\x89PNG")
    assert not (tmp_path / "chart.pdf").exists()


def test_png_request_falls_back_to_pdf_when_pillow_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("reportlab")
    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("Pillow intentionally unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    files = export_static_chart(
        tmp_path,
        prompt="Make a PNG bar chart Q1 120 Q2 135",
        plan=_plan(),
    )
    assert files[0] == "chart.pdf"
    assert (tmp_path / "chart.pdf").read_bytes().startswith(b"%PDF-")
    assert not (tmp_path / "chart.png").exists()


def test_is_canvas_task_accepts_named_png_output() -> None:
    # chart.png must be in the canvas export allowlist so an explicit png ask
    # is not rejected as a non-canvas named deliverable.
    assert is_canvas_task("make a bar chart and save chart.png")


def test_static_chart_export_fails_closed_when_reportlab_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("reportlab"):
            raise ImportError("reportlab intentionally unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(ChartExportUnavailable, match="reportlab package is not installed"):
        export_static_chart(
            tmp_path,
            prompt="Create a bar chart showing Q1 120 and Q2 135",
            plan=_plan(),
        )

    assert not (tmp_path / "chart.pdf").exists()
    assert not (tmp_path / "chart-data.csv").exists()
