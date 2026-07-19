from __future__ import annotations

import pytest

from thomas.server.chat_delegation_canvas import is_canvas_task


@pytest.mark.parametrize(
    "prompt",
    [
        "Create a bar chart showing Q1 120 and Q2 135",
        "Visualize sales as a heatmap",
        "Draw a flow diagram of the checkout process",
        "Make a mind map for the product launch",
        "Plot Q1 120 and Q2 135",
        "Build a playable browser game",
        "Draw an SVG logo for Cedar Labs",
        "Create a bar chart from sales.csv",
        (
            "Create one static bar chart showing Alpha 3, Beta 7, and Gamma 5. "
            "Render it live on Canvas and deliver chart.pdf with chart-data.csv."
        ),
        "An infographic about household energy use",
    ],
)
def test_canvas_intent_accepts_actual_visual_creation_requests(prompt: str) -> None:
    assert is_canvas_task(prompt)


@pytest.mark.parametrize(
    "prompt",
    [
        "Explain what a bar chart is",
        "Analyze the chart I attached",
        "Create a chart of accounts for my business",
        "Design a graph database schema",
        "Explain graph theory in plain English",
        "Summarize the plot of the book",
        "Review the patient's medical chart",
        "Write a report about dashboard adoption",
        (
            "Create exactly two downloadable SVG image artifacts named original.svg and edited.svg. "
            "Use fs.write_file and fs.read_file to verify both files."
        ),
        "Create hero.svg and badge.svg",
        "Create sales_chart.md with Mermaid",
        "Build a dashboard in app.vue",
        "Create a diagram saved as diagram.yaml",
        "Generate the query as report.sql",
        "Build the service in main.go",
        "Create the parser as parser.rs",
        "Export the result to diagram.xml",
        "Create a bar chart and save the result as sales-chart.pdf",
    ],
)
def test_canvas_intent_rejects_visual_words_without_visual_creation(prompt: str) -> None:
    assert not is_canvas_task(prompt)
