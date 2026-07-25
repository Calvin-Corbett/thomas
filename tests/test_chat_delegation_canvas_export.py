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


def test_function_words_in_the_request_are_not_chart_data() -> None:
    """Backing data must describe the chart, not the sentence that asked for it.

    Live incident, 2026-07-24: "make me a graph of the most popular programming
    languages in 2026" scraped as the single row `in = 2026`, and because prompt
    data outranks the rendered plan, the exported chart-data.csv contained that
    instead of the seven bars actually drawn.
    """
    plan = json.dumps(
        {
            "title": "Most Popular Programming Languages",
            "elements": [
                {"kind": "number", "label": "Python", "value": 57},
                {"kind": "number", "label": "JavaScript", "value": 55},
            ],
        }
    )
    title, rows = extract_chart_data(
        "make me a graph of the most popular programming languages in 2026", plan
    )

    assert title == "Most Popular Programming Languages"
    assert [(row.label, row.value) for row in rows] == [("Python", 57.0), ("JavaScript", 55.0)]
    assert "in" not in {row.label.casefold() for row in rows}


def test_backing_data_comes_from_the_chart_that_was_drawn() -> None:
    """The rendered document outranks the plan, and beats prose around it.

    Live incident, 2026-07-24: a chart showing Electricity 45% through Other
    renewables 5% shipped a spreadsheet reading "Series 1, 100", because the
    plan's elements carried no usable label/value pairs and nothing consulted
    the page itself.
    """
    rendered = (
        "<html><head><style>.bar{display:grid}</style></head><body>"
        "<h1>Household Energy Use by Source &mdash; 2026</h1>"
        "<p>Illustrative projected share of annual household site energy use</p>"
        "<ul><li>Electricity &middot; 45%</li><li>Natural gas &middot; 35%</li>"
        "<li>LPG / propane &middot; 8%</li><li>Heating oil &middot; 7%</li>"
        "<li>Other renewables &middot; 5%</li></ul></body></html>"
    ).replace("&mdash;", "—").replace("&middot;", "·")

    _, rows = extract_chart_data("make me a chart of household energy use", "", rendered)
    pairs = [(row.label, row.value) for row in rows]

    assert pairs == [
        ("Electricity", 45.0),
        ("Natural gas", 35.0),
        ("LPG / propane", 8.0),
        ("Heating oil", 7.0),
        ("Other renewables", 5.0),
    ]
    # The heading's trailing year must not become a data point.
    assert 2026.0 not in {value for _, value in pairs}


def test_axis_ticks_and_source_notes_are_not_data_rows() -> None:
    """Live incident, 2026-07-24: a commute chart exported a seventh row,
    "ACS 1-Year estimates, 0" -- the y-axis baseline glued to the source note.
    The real series each carry a legend marker; the axis label does not."""
    rendered = (
        "<html><body><h1>How Americans Commute to Work</h1>"
        "<p>Source: U.S. Census Bureau, 2023 ACS 1-Year estimates</p>"
        "<span>0</span><span>% of workers</span>"
        "<ul><li>&#9679; Drive alone 68.7%</li><li>&#9679; Carpool 8.6%</li>"
        "<li>&#9679; Public transit 3.6%</li><li>&#9679; Worked at home 13.7%</li></ul>"
        "</body></html>"
    ).replace("&#9679;", "●")

    _, rows = extract_chart_data("chart showing how people commute to work", "", rendered)
    labels = [row.label for row in rows]

    assert labels == ["Drive alone", "Carpool", "Public transit", "Worked at home"]
    assert not any(row.value == 0 for row in rows)


# A bar chart the way these are actually drawn: absolutely positioned bars whose
# HEIGHT encodes the value, an axis label row sharing one y coordinate, and
# per-bar value labels that read 0 because the bars animate upward.
_AXIS_CHART = (
    '<div style="left:100px;top:40px;">Coffee Consumption by Country</div>'
    '<div style="left:60px;top:200px;">12</div>'
    '<div style="left:60px;top:300px;">6</div>'
    '<div style="left:60px;top:400px;">0</div>'
    '<div class="el grow-y" style="left:130px;top:180px;width:64px;height:240px;"></div>'
    '<div class="el grow-y" style="left:238px;top:222px;width:64px;height:198px;"></div>'
    '<div class="el grow-y" style="left:346px;top:240px;width:64px;height:180px;"></div>'
    '<div style="left:148px;top:445px;">Finland</div>'
    '<div style="left:256px;top:445px;">Norway</div>'
    '<div style="left:364px;top:445px;">Iceland</div>'
)


def test_plan_values_take_the_names_the_chart_is_drawn_with() -> None:
    """Live incident, 2026-07-24: a coffee chart reading Finland, Norway,
    Iceland exported "Series 1..5". The plan carried the numbers and no labels,
    the render carried the labels, and nothing joined them. An axis label row is
    a run of text boxes sharing a y coordinate."""
    plan = json.dumps(
        {
            "title": "Coffee Consumption by Country",
            "elements": [
                {"kind": "number", "value": 12},
                {"kind": "number", "value": 9.9},
                {"kind": "number", "value": 9},
            ],
        }
    )
    _, rows = extract_chart_data("chart of coffee consumption by country", plan, _AXIS_CHART)

    assert [(row.label, row.value) for row in rows] == [
        ("Finland", 12.0),
        ("Norway", 9.9),
        ("Iceland", 9.0),
    ]


def test_values_follow_the_bars_not_the_plans_ordering() -> None:
    """Live incident, 2026-07-24: a languages chart exported French 1528 above
    English 1184, because the plan lists its numbers in a different order from
    the one the bars are drawn in. Count agreement says nothing about order, so
    the join goes through the geometry: the tallest bar owns the largest value.
    """
    # Deliberately shuffled: the plan's first number is NOT the first bar's.
    plan = json.dumps(
        {
            "title": "Coffee",
            "elements": [
                {"kind": "number", "value": 9.0},
                {"kind": "number", "value": 12.0},
                {"kind": "number", "value": 9.9},
            ],
        }
    )
    _, rows = extract_chart_data("chart of coffee consumption", plan, _AXIS_CHART)

    # Bar heights are Finland 240 > Norway 198 > Iceland 180.
    assert [(row.label, row.value) for row in rows] == [
        ("Finland", 12.0),
        ("Norway", 9.9),
        ("Iceland", 9.0),
    ]


def test_names_are_not_guessed_without_bars_to_match_against() -> None:
    """Without geometry there is no way to know which value belongs to which
    label, so the placeholders stay rather than being confidently wrong."""
    plan = json.dumps(
        {"title": "Coffee", "elements": [{"kind": "number", "value": v} for v in (12, 9.9, 9)]}
    )
    label_only = (
        '<div style="left:148px;top:445px;">Finland</div>'
        '<div style="left:256px;top:445px;">Norway</div>'
        '<div style="left:364px;top:445px;">Iceland</div>'
    )
    _, rows = extract_chart_data("chart of coffee consumption", plan, label_only)

    assert [row.label for row in rows] == ["Series 1", "Series 2", "Series 3"]


def test_names_are_not_guessed_when_the_counts_disagree() -> None:
    """Pairing four values against three names would mean choosing which value
    belongs to which label. Confidently wrong labels are worse than honest
    placeholders."""
    plan = json.dumps(
        {
            "title": "Coffee",
            "elements": [{"kind": "number", "value": v} for v in (12, 9.9, 9, 8.7)],
        }
    )
    _, rows = extract_chart_data("chart of coffee consumption", plan, _AXIS_CHART)

    assert [row.label for row in rows] == ["Series 1", "Series 2", "Series 3", "Series 4"]


def test_axis_ticks_are_never_mistaken_for_category_names() -> None:
    from thomas.server.chat_delegation_canvas_export import _rendered_axis_labels

    assert _rendered_axis_labels(_AXIS_CHART) == ["Finland", "Norway", "Iceland"]


def test_labels_already_supplied_by_the_plan_are_left_alone() -> None:
    plan = json.dumps(
        {
            "title": "Coffee",
            "elements": [
                {"kind": "number", "label": "Brazil", "value": 5},
                {"kind": "number", "label": "Peru", "value": 4},
                {"kind": "number", "label": "Kenya", "value": 3},
            ],
        }
    )
    _, rows = extract_chart_data("chart of coffee", plan, _AXIS_CHART)

    assert [row.label for row in rows] == ["Brazil", "Peru", "Kenya"]


def test_prompt_supplied_values_still_outrank_the_rendered_page() -> None:
    rendered = "<html><body><p>Alpha &middot; 99%</p><p>Beta &middot; 98%</p></body></html>".replace(
        "&middot;", "·"
    )
    _, rows = extract_chart_data("chart Q1 120 Q2 135", _plan(), rendered)

    assert [(row.label, row.value) for row in rows] == [("Q1", 120.0), ("Q2", 135.0)]


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
