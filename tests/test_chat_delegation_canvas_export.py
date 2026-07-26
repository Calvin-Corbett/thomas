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
    _printed_value,
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


def _banana_plan() -> str:
    """The plan shape that shipped "Series 1..5" for a banana chart.

    Values live on `number` elements; the variety names are separate `text`
    elements sitting under each bar, exactly as the planner is instructed.
    """
    elements = []
    varieties = [("Cavendish", 9.2), ("Gros Michel", 9.0), ("Lady Finger", 8.8)]
    for i, (name, score) in enumerate(varieties):
        x = 120 + i * 180
        elements.append({"kind": "bar", "geometry": {"x": x, "y": 300, "w": 80, "h": 150}})
        elements.append({"kind": "number", "value": score, "geometry": {"x": x, "y": 280}})
        elements.append({"kind": "text", "label": name, "geometry": {"x": x, "y": 460}})
    return json.dumps({"title": "Best Banana Varieties", "elements": elements})


def test_axis_labels_are_paired_with_their_values() -> None:
    """The regression: a graph of banana varieties that named no bananas.

    The exporter read only `number` elements, found no labels on them, and wrote
    Series 1..5 -- real data under meaningless names.
    """
    title, rows = extract_chart_data("make me a graph of the best banana varieties", _banana_plan())

    assert title == "Best Banana Varieties"
    assert [(r.label, r.value) for r in rows] == [
        ("Cavendish", 9.2),
        ("Gros Michel", 9.0),
        ("Lady Finger", 8.8),
    ]


def test_pairing_never_substitutes_geometry_for_a_value() -> None:
    """Guards the defect that got the previous attempt reverted: bar heights
    exported as data. The bars above are 150px tall; the values are ~9."""
    _title, rows = extract_chart_data("graph the best banana varieties", _banana_plan())

    assert all(r.value < 100 for r in rows), [r.value for r in rows]
    assert 150.0 not in [r.value for r in rows]


def test_a_distant_label_is_not_borrowed_for_a_bar() -> None:
    """A label three bars away is not this bar's label -- better an honest
    placeholder than a confidently wrong name."""
    plan = json.dumps(
        {
            "title": "Sparse",
            "elements": [
                {"kind": "number", "value": 5, "geometry": {"x": 100, "y": 280}},
                {"kind": "number", "value": 7, "geometry": {"x": 200, "y": 280}},
                {"kind": "text", "label": "Somewhere Else", "geometry": {"x": 640, "y": 460}},
            ],
        }
    )
    _title, rows = extract_chart_data("bar chart of things", plan)

    assert [(r.label, r.value) for r in rows] == [("Series 1", 5.0), ("Series 2", 7.0)]


def test_an_explicit_label_on_the_number_still_wins() -> None:
    """Pairing is a fallback, not an override."""
    plan = json.dumps(
        {
            "title": "Explicit",
            "elements": [
                {"kind": "number", "label": "Q1", "value": 120, "geometry": {"x": 100, "y": 280}},
                {"kind": "text", "label": "Not This", "geometry": {"x": 100, "y": 460}},
                {"kind": "number", "label": "Q2", "value": 135, "geometry": {"x": 220, "y": 280}},
                {"kind": "text", "label": "Nor This", "geometry": {"x": 220, "y": 460}},
            ],
        }
    )
    _title, rows = extract_chart_data("bar chart", plan)

    assert [(r.label, r.value) for r in rows] == [("Q1", 120.0), ("Q2", 135.0)]


def test_each_label_is_claimed_by_only_one_value() -> None:
    """Two bars must not both take the same axis label."""
    plan = json.dumps(
        {
            "title": "Two",
            "elements": [
                {"kind": "number", "value": 1, "geometry": {"x": 100, "y": 280}},
                {"kind": "number", "value": 2, "geometry": {"x": 110, "y": 280}},
                {"kind": "text", "label": "Alpha", "geometry": {"x": 100, "y": 460}},
                {"kind": "text", "label": "Beta", "geometry": {"x": 112, "y": 460}},
            ],
        }
    )
    _title, rows = extract_chart_data("bar chart", plan)

    labels = [r.label for r in rows]
    assert len(set(labels)) == len(labels), labels
    assert set(labels) == {"Alpha", "Beta"}


def test_a_plan_with_no_text_elements_is_unchanged() -> None:
    """Pairing must not disturb the plans that already worked."""
    title, rows = extract_chart_data("quarterly revenue chart", _plan())

    assert title == "Quarterly Revenue"
    assert [(r.label, r.value) for r in rows] == [("Q1", 120.0), ("Q2", 135.0)]


def test_a_drawing_of_a_chart_is_not_chart_data() -> None:
    """The defect behind Calvin's "make me a chart of the most spoken
    languages": the plan drew eight `bar` elements and stated no values, so the
    export fell back to the bars' pixel geometry and shipped eight rows reading
    `Series N, 24` -- eight bars, 24 pixels each -- as verified backing data.
    A reader cannot tell that from a real measurement."""
    plan = json.dumps(
        {
            "title": "Most Spoken Languages",
            "elements": [
                {"kind": "bar", "geometry": {"x": 90 + i * 70, "y": 300, "w": 24, "h": 24}}
                for i in range(8)
            ],
        }
    )

    _title, rows = extract_chart_data("make me a chart of the most spoken languages", plan)

    assert rows == []


def test_no_values_means_no_invented_single_row() -> None:
    """An empty plan used to yield a literal ChartDatum("Series 1", 1.0)."""
    _title, rows = extract_chart_data("make me a bar chart of something", "{}")

    assert rows == []


def test_export_refuses_to_write_files_it_cannot_back(tmp_path: Path) -> None:
    """Fail the export, not silently write a PDF and spreadsheet of inventions."""
    plan = json.dumps(
        {"title": "Drawing only", "elements": [{"kind": "bar", "geometry": {"h": 24}}]}
    )

    with pytest.raises(ChartExportUnavailable, match="no chart values"):
        export_static_chart(tmp_path, prompt="make me a bar chart", plan=plan)

    assert not (tmp_path / "chart.pdf").exists()
    assert not (tmp_path / "chart-data.csv").exists()
    assert not (tmp_path / "chart-data.xlsx").exists()


def test_a_plan_that_states_its_values_still_exports(tmp_path: Path) -> None:
    """The refusal must be narrow: real data still ships."""
    pytest.importorskip("reportlab")
    files = export_static_chart(
        tmp_path, prompt="Create a bar chart showing Q1 120 and Q2 135", plan=_plan()
    )

    assert files[:2] == ["chart.pdf", "chart-data.csv"]


def test_rows_follow_the_chart_not_the_plan_element_order() -> None:
    """Calvin's "most spoken languages" chart drew English first and tallest,
    but the planner emitted that element last, so the exported table listed
    English (1528) beneath Arabic (335). Every pair was correct and the table
    still read as wrong."""
    elements = [
        {"kind": "number", "value": 1184, "geometry": {"x": 261, "y": 222}},
        {"kind": "text", "label": "Mandarin Chinese", "geometry": {"x": 261, "y": 450}},
        {"kind": "number", "value": 609, "geometry": {"x": 371, "y": 309}},
        {"kind": "text", "label": "Hindi", "geometry": {"x": 371, "y": 450}},
        {"kind": "number", "value": 335, "geometry": {"x": 591, "y": 350}},
        {"kind": "text", "label": "Standard Arabic", "geometry": {"x": 591, "y": 450}},
        # Drawn first in the chart, emitted last in the plan.
        {"kind": "number", "value": 1528, "geometry": {"x": 151, "y": 171}},
        {"kind": "text", "label": "English", "geometry": {"x": 151, "y": 450}},
    ]
    plan = json.dumps({"title": "Most Spoken Languages", "elements": elements})

    _title, rows = extract_chart_data("chart of the most spoken languages", plan)

    assert [(r.label, r.value) for r in rows] == [
        ("English", 1528.0),
        ("Mandarin Chinese", 1184.0),
        ("Hindi", 609.0),
        ("Standard Arabic", 335.0),
    ]


def test_a_horizontal_bar_chart_is_ordered_top_to_bottom() -> None:
    """Orientation must not be assumed. In a horizontal bar chart the value
    label rides sideways with the bar, so sorting on x would order the table by
    magnitude rather than by category."""
    elements = []
    for i, (name, value) in enumerate(
        [("Alpha", 90.0), ("Beta", 10.0), ("Gamma", 50.0)]
    ):
        y = 120 + i * 80
        # Value label sits at the END of the bar -- its x tracks the value.
        elements.append({"kind": "number", "value": value, "geometry": {"x": 100 + value * 4, "y": y}})
        elements.append({"kind": "text", "label": name, "geometry": {"x": 60, "y": y + 6}})
    plan = json.dumps({"title": "Horizontal", "elements": elements})

    _title, rows = extract_chart_data("bar chart", plan)

    assert [r.label for r in rows] == ["Alpha", "Beta", "Gamma"]


def test_a_partially_paired_plan_is_not_reshuffled() -> None:
    """Reordering on incomplete position data would be worse than plan order."""
    plan = json.dumps(
        {
            "title": "Partial",
            "elements": [
                {"kind": "number", "label": "First", "value": 1, "geometry": {"x": 400, "y": 200}},
                {"kind": "number", "label": "Second", "value": 2},
                {"kind": "text", "label": "Zed", "geometry": {"x": 400, "y": 460}},
            ],
        }
    )

    _title, rows = extract_chart_data("bar chart", plan)

    assert [r.label for r in rows] == ["First", "Second"]


def _commute_plan() -> str:
    """The real shape of Calvin's commute chart: every value is PRINTED as a
    text element and the plan declares no `number` element at all."""
    rows = [("Drive alone", "68.7%"), ("Work from home", "15.2%"), ("Carpool", "8.6%"),
            ("Transit", "3.1%"), ("Walk", "2.5%"), ("Other", "1.9%")]
    elements = [
        {"kind": "text", "label": "How Americans Commute to Work", "geometry": {"x": 64, "y": 60}},
        {"kind": "text", "label": "Workers age 16+, United States, 2022", "geometry": {"x": 64, "y": 86}},
        {"kind": "text", "label": "Source: U.S. Census Bureau, ACS 2022 (1-year estimates)",
         "geometry": {"x": 64, "y": 478}},
    ]
    for i, (name, printed) in enumerate(rows):
        x = 108 + i * 104
        elements.append({"kind": "text", "label": printed, "geometry": {"x": x, "y": 150 + i * 40}})
        elements.append({"kind": "text", "label": name, "geometry": {"x": x, "y": 430}})
    return json.dumps({"title": "How Americans Commute to Work", "elements": elements})


def test_values_the_plan_prints_as_text_are_still_data() -> None:
    """Refusing to read printed values left a chart of real, visible data with
    no data file beside it -- the chart clearly showed 68.7% Drive alone."""
    title, rows = extract_chart_data("make me a chart showing how people commute to work", _commute_plan())

    assert title == "How Americans Commute to Work"
    assert [(r.label, r.value) for r in rows] == [
        ("Drive alone", 68.7),
        ("Work from home", 15.2),
        ("Carpool", 8.6),
        ("Transit", 3.1),
        ("Walk", 2.5),
        ("Other", 1.9),
    ]


def test_a_source_citation_is_not_a_data_row() -> None:
    """The original export shipped a leading row `ACS 1-Year estimates, 0`."""
    _title, rows = extract_chart_data("chart how people commute", _commute_plan())

    assert all("Source" not in r.label and "ACS" not in r.label for r in rows)
    assert all(r.value != 0 for r in rows)


def test_axis_ticks_are_not_mistaken_for_values() -> None:
    """Ticks print as numbers too. They are excluded by requiring a value to
    pair with a CATEGORY label -- ticks have no category beneath them."""
    elements = [
        {"kind": "text", "label": tick, "geometry": {"x": 84, "y": 200 + i * 75}}
        for i, tick in enumerate(["1,500", "1,000", "500", "0"])
    ]
    for i, (name, printed) in enumerate([("English", "1528"), ("Mandarin", "1184")]):
        x = 151 + i * 110
        elements.append({"kind": "text", "label": printed, "geometry": {"x": x, "y": 171}})
        elements.append({"kind": "text", "label": name, "geometry": {"x": x, "y": 450}})
    plan = json.dumps({"title": "Languages", "elements": elements})

    _title, rows = extract_chart_data("chart the most spoken languages", plan)

    assert [(r.label, r.value) for r in rows] == [("English", 1528.0), ("Mandarin", 1184.0)]


def test_a_year_in_a_caption_is_not_a_data_point() -> None:
    """The whole string must be the number, or a subtitle mentioning 2022
    becomes a row."""
    assert _printed_value("2022") == 2022.0
    assert _printed_value("Workers age 16+, United States, 2022") is None
    assert _printed_value("68.7%") == 68.7
    assert _printed_value("1,528") == 1528.0
    assert _printed_value("$1,200") == 1200.0
    assert _printed_value("Q1") is None
    assert _printed_value("") is None


def test_printed_values_still_refuse_a_chart_of_one() -> None:
    """One paired value is not a chart; better no data file than a lone row."""
    elements = [
        {"kind": "text", "label": "42", "geometry": {"x": 100, "y": 150}},
        {"kind": "text", "label": "Only", "geometry": {"x": 100, "y": 430}},
    ]
    plan = json.dumps({"title": "Lonely", "elements": elements})

    _title, rows = extract_chart_data("bar chart", plan)

    assert rows == []


def test_a_single_bar_is_not_a_chart() -> None:
    """Calvin's household-energy chart shipped the lone row `Series 1, 100`,
    and a rerun of his commute chart produced one 100% bar subtitled
    "Illustrative distribution". Attaching a one-row spreadsheet presents a
    model's hedge as a finding."""
    plan = json.dumps(
        {
            "title": "How People Commute to Work",
            "elements": [
                {"kind": "number", "value": 100, "geometry": {"x": 240, "y": 282}},
                {"kind": "text", "label": "% of workers", "geometry": {"x": 240, "y": 316}},
            ],
        }
    )

    _title, rows = extract_chart_data("make me a chart showing how people commute to work", plan)

    assert rows == []


def test_two_real_rows_are_still_enough() -> None:
    """The floor must not reject genuinely small charts."""
    _title, rows = extract_chart_data("quarterly revenue chart", _plan())

    assert [(r.label, r.value) for r in rows] == [("Q1", 120.0), ("Q2", 135.0)]
