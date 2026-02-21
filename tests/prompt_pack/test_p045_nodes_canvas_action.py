import importlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thomas.nodes.p045_nodes_canvas_action import (
    CanvasActionConfigError,
    CanvasActionInputError,
    FileCanvasStateStore,
    NodesCanvasActionRequest,
    run_nodes_canvas_action,
)


runner = CliRunner()
cli_mod = importlib.import_module("thomas.cli.commands.nodes.p045_nodes_canvas_action")


def _read_store(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def test_run_pan_persists_state(tmp_path: Path) -> None:
    store_path = tmp_path / "state" / "nodes_canvas_state.json"
    store = FileCanvasStateStore(store_path)

    # Start from implicit defaults and pan.
    req = NodesCanvasActionRequest(
        canvas_id="c1",
        operation="pan",
        payload={"dx": 5, "dy": -1.5},
        dry_run=False,
    )
    res = run_nodes_canvas_action(req, store=store)

    assert res.ok is True
    assert res.canvas_id == "c1"
    assert res.operation == "pan"
    assert res.state.viewport.x == pytest.approx(5.0)
    assert res.state.viewport.y == pytest.approx(-1.5)

    raw = _read_store(store_path)
    assert raw["c1"]["viewport"]["x"] == pytest.approx(5.0)
    assert raw["c1"]["viewport"]["y"] == pytest.approx(-1.5)


def test_dry_run_does_not_persist(tmp_path: Path) -> None:
    store_path = tmp_path / "state" / "nodes_canvas_state.json"
    store = FileCanvasStateStore(store_path)

    req = NodesCanvasActionRequest(
        canvas_id="c1",
        operation="zoom",
        payload={"factor": 2},
        dry_run=True,
    )
    res = run_nodes_canvas_action(req, store=store)

    assert res.state.viewport.zoom == pytest.approx(2.0)
    assert store_path.exists() is False  # no write


def test_unknown_operation_is_input_error(tmp_path: Path) -> None:
    store_path = tmp_path / "state" / "nodes_canvas_state.json"
    store = FileCanvasStateStore(store_path)

    req = NodesCanvasActionRequest(canvas_id="default", operation="teleport", payload={})
    with pytest.raises(CanvasActionInputError) as ei:
        run_nodes_canvas_action(req, store=store)
    assert ei.value.code == "unknown_operation"


def test_invalid_state_store_json_is_config_error(tmp_path: Path) -> None:
    store_path = tmp_path / "state" / "nodes_canvas_state.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("[not-an-object]", encoding="utf-8")

    store = FileCanvasStateStore(store_path)
    req = NodesCanvasActionRequest(canvas_id="default", operation="clear-selection", payload={})
    with pytest.raises(CanvasActionConfigError) as ei:
        run_nodes_canvas_action(req, store=store)
    assert ei.value.code == "invalid_state_store"


def test_cli_json_success(tmp_path: Path) -> None:
    store_path = tmp_path / "state" / "nodes_canvas_state.json"

    result = runner.invoke(
        cli_mod.app,
        [
            "action",
            "select",
            "--canvas-id",
            "default",
            "--payload",
            json.dumps({"node_ids": ["n1", "n1", "n2"]}),
            "--state-path",
            str(store_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["operation"] == "select"
    assert out["state"]["selected_node_ids"] == ["n1", "n2"]


def test_cli_invalid_payload_json(tmp_path: Path) -> None:
    store_path = tmp_path / "state" / "nodes_canvas_state.json"

    result = runner.invoke(
        cli_mod.app,
        [
            "action",
            "pan",
            "--canvas-id",
            "default",
            "--payload",
            "{not json}",
            "--state-path",
            str(store_path),
            "--json",
        ],
    )

    assert result.exit_code == 2
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_payload_json"
