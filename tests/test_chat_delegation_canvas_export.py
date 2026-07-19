from __future__ import annotations

import builtins
import csv
import json
from pathlib import Path

import pytest

from thomas.server.chat_delegation_canvas_export import (
    ChartExportUnavailable,
    export_static_chart,
    extract_chart_data,
    is_static_chart_request,
)


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
