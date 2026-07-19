from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.core import task_bot_runtime
from thomas.server.chat_delegation_canvas import canvas_set_plan, canvas_start
from thomas.server.chat_delegation_canvas_completion import complete_canvas_delivery


def _execution(repo_root: Path, summary: str) -> str:
    return str(
        task_bot_runtime.create_execution(
            session_id="canvas-session",
            summary=summary,
            repo_root=repo_root,
        )["execution_id"]
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


def test_static_chart_completion_delivers_pdf_and_data_not_html(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    execution_id = _execution(tmp_path, "Create a quarterly revenue chart")
    canvas_start(execution_id, "Quarterly Revenue")
    canvas_set_plan(execution_id, _plan())

    record, summary = complete_canvas_delivery(
        execution_id=execution_id,
        prompt="Create a static bar chart showing Q1 120 and Q2 135",
        html="<!doctype html><title>Quarterly Revenue</title>",
        actor="Taylor",
        repo_root=tmp_path,
        workspace_for=lambda _: tmp_path / "workspace",
    )

    artifact_names = {str(row["path"]) for row in record["proof"]["artifacts"]}
    assert record["state"] == "completed"
    assert record["proof_status"] == "verified"
    assert summary == "Reviewed the live chart and delivered chart.pdf with backing data."
    assert {"chart.pdf", "chart-data.csv"} <= artifact_names
    assert "index.html" not in artifact_names
    assert (tmp_path / "workspace" / "chart.pdf").read_bytes().startswith(b"%PDF-")


def test_interactive_canvas_completion_keeps_html_as_deliverable(tmp_path: Path) -> None:
    execution_id = _execution(tmp_path, "Create an interactive chart")

    record, summary = complete_canvas_delivery(
        execution_id=execution_id,
        prompt="Create an interactive chart with hover tooltips",
        html="<!doctype html><button>Show details</button>",
        actor="Taylor",
        repo_root=tmp_path,
        workspace_for=lambda _: tmp_path / "workspace",
    )

    assert [row["path"] for row in record["proof"]["artifacts"]] == ["index.html"]
    assert summary == "Reviewed and rendered index.html on the canvas."
    assert record["state"] == "completed"
    assert record["proof_status"] == "verified"


def test_canvas_completion_fails_closed_when_proof_persistence_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_id = _execution(tmp_path, "Create an interactive chart")

    def fail_attach(*_args: object, **_kwargs: object) -> None:
        raise OSError("proof ledger unavailable")

    monkeypatch.setattr(task_bot_runtime, "attach_proof", fail_attach)

    with pytest.raises(OSError, match="proof ledger unavailable"):
        complete_canvas_delivery(
            execution_id=execution_id,
            prompt="Create an interactive chart with hover tooltips",
            html="<!doctype html><button>Show details</button>",
            actor="Taylor",
            repo_root=tmp_path,
            workspace_for=lambda _: tmp_path / "workspace",
        )

    record = task_bot_runtime.get_execution(execution_id, tmp_path)
    assert record is not None
    assert record["state"] != "completed"
    assert record["proof_status"] != "verified"


def test_canvas_completion_enforces_read_only_and_allowed_paths(tmp_path: Path) -> None:
    execution_id = _execution(tmp_path, "Create an interactive chart")
    kwargs = {
        "execution_id": execution_id,
        "prompt": "Create an interactive chart",
        "html": "<!doctype html><title>Chart</title>",
        "actor": "Taylor",
        "repo_root": tmp_path,
        "workspace_for": lambda _: tmp_path / "workspace",
    }

    with pytest.raises(PermissionError, match="read-only"):
        complete_canvas_delivery(**kwargs, file_access=0)
    with pytest.raises(PermissionError, match="allowed_paths"):
        complete_canvas_delivery(**kwargs, allowed_paths=(str(tmp_path / "different"),))
    assert not (tmp_path / "workspace" / "index.html").exists()
